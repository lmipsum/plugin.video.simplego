from resources.lib.provider import servicecert


def test_unwrap_service_certificate():
    cert = bytes(range(200))
    # SignedMessage{type: SERVICE_CERTIFICATE (5), msg: <cert>}; 200 needs a two-byte varint length.
    msg = b"\x08\x05\x12\xc8\x01" + cert
    assert servicecert.unwrap(msg) == cert


def test_unwrap_service_certificate_rejects_other_messages():
    assert servicecert.unwrap(b"\x08\x02\x12\x01x") is None
    # Truncated payload.
    assert servicecert.unwrap(b"\x08\x05\x12\x10abc") is None
