import base64
import hashlib
import random

from resources.lib.provider import rsaoaep


def _prime(bits, rng):
    while True:
        n = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)):
            return n


def _der(tag, content):
    size = len(content)
    if size < 0x80:
        length = bytes([size])
    else:
        raw = size.to_bytes((size.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + length + content


def _integer(value):
    raw = value.to_bytes((value.bit_length() + 8) // 8, "big")  # a leading zero keeps it positive
    return _der(0x02, raw)


def _key(rng):
    e = 65537
    while True:
        p, q = _prime(512, rng), _prime(512, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            break
    n = p * q
    rsa_key = _der(0x30, _integer(n) + _integer(e))
    algorithm = _der(0x30, bytes.fromhex("06092a864886f70d0101010500"))
    spki = _der(0x30, algorithm + _der(0x03, b"\x00" + rsa_key))
    return base64.b64encode(spki).decode(), n, pow(e, -1, phi)


def _decrypt(ciphertext, n, d):
    size = (n.bit_length() + 7) // 8
    em = pow(int.from_bytes(base64.b64decode(ciphertext), "big"), d, n).to_bytes(size, "big")
    hlen = 20
    masked_seed, masked_block = em[1 : 1 + hlen], em[1 + hlen :]
    seed = bytes(a ^ b for a, b in zip(masked_seed, rsaoaep._mgf1(masked_block, hlen)))
    block = bytes(a ^ b for a, b in zip(masked_block, rsaoaep._mgf1(seed, size - hlen - 1)))
    assert em[0] == 0 and block[:hlen] == hashlib.sha1(b"").digest()
    return block[block.index(b"\x01", hlen) + 1 :]


def test_oaep_round_trip():
    spki, n, d = _key(random.Random(1))
    assert rsaoaep.public_key(spki) == (n, 65537)
    first, second = rsaoaep.encrypt(spki, b"1234"), rsaoaep.encrypt(spki, b"1234")
    assert len(base64.b64decode(first)) == 128  # as the web player's: a 1024-bit key
    assert first != second  # a random seed each time
    assert _decrypt(first, n, d) == b"1234" and _decrypt(second, n, d) == b"1234"
