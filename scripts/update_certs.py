#!/usr/bin/env python3
"""Fetch the certificate chain the web player's host fails to send, check it, and ship it.

Follows the AIA issuer addresses from the host's certificate to the intermediate and
to a cross-signed root that Kodi's certifi trusts, checking every signature. Compares
with resources/certs (--write replaces them); the printed SHA-256 fingerprints go into
tests/test_certs.py.

    python scripts/update_certs.py           # fetch and check only
    python scripts/update_certs.py --write   # ship the chain fetched
"""

import argparse
import hashlib
import os
import socket
import ssl
import sys
import warnings

import certifi
import requests
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.utils import CryptographyDeprecationWarning
from cryptography.x509.oid import AuthorityInformationAccessOID
from cryptography.x509.oid import ExtensionOID

HOST = "player.telekomtvgo.hu"
CERTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "certs")
FILES = {"intermediate": "intermediate.crt", "cross_signed": "cross-signed-root.crt"}


def host_certificate():
    """Return the host's own certificate, as it sends it (unverified: the chain is what is missing)."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((HOST, 443), timeout=20) as sock, context.wrap_socket(sock, server_hostname=HOST) as tls:
        return x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))


def issuers_of(cert):
    """Return the certificates found at the issuer address the certificate names (.crt or .p7c)."""
    aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    url = next(d.access_location.value for d in aia if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS)
    data = requests.get(url, timeout=20).content
    if url.endswith(".p7c"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # Sectigo's bundle is BER, not strict DER
            return pkcs7.load_der_pkcs7_certificates(data)
    return [x509.load_der_x509_certificate(data)]


def certifi_roots():
    """Return the roots of the certifi version Kodi ships (pinned in requirements-dev.txt)."""
    with open(os.path.join(os.path.dirname(CERTS), "..", "requirements-dev.txt"), encoding="utf-8") as f:
        pinned = next(line.split("==")[1].strip() for line in f if line.startswith("certifi=="))
    if tuple(map(int, certifi.__version__.split("."))) != tuple(map(int, pinned.split("."))):
        sys.exit("certifi %s is not Kodi's (%s): pip install -r requirements-dev.txt" % (certifi.__version__, pinned))
    with warnings.catch_warnings():
        # An old certifi root has a serial newer cryptography warns about; not ours.
        warnings.simplefilter("ignore", CryptographyDeprecationWarning)
        with open(certifi.where(), "rb") as f:
            return x509.load_pem_x509_certificates(f.read())


def chain():
    """Return (intermediate, cross-signed root), each checked against the one below it and certifi."""
    leaf = host_certificate()
    intermediate = next(c for c in issuers_of(leaf) if c.subject == leaf.issuer)
    leaf.verify_directly_issued_by(intermediate)
    roots = {root.subject: root for root in certifi_roots()}
    # Kodi's certifi lacks the self-signed issuer: take the longest-valid cross-signed copy.
    copies = [c for c in issuers_of(intermediate) if c.subject == intermediate.issuer != c.issuer and c.issuer in roots]
    cross_signed = max(copies, key=lambda c: c.not_valid_after_utc)
    intermediate.verify_directly_issued_by(cross_signed)
    cross_signed.verify_directly_issued_by(roots[cross_signed.issuer])
    return intermediate, cross_signed


def fingerprint(cert):
    return hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true", help="replace the certificates in resources/certs")
    args = parser.parse_args()
    found = dict(zip(("intermediate", "cross_signed"), chain()))
    changed = False
    for role, cert in found.items():
        path = os.path.join(CERTS, FILES[role])
        pem = cert.public_bytes(Encoding.PEM)
        same = os.path.exists(path) and open(path, "rb").read() == pem
        changed = changed or not same
        print(
            "%-20s %s\n  %s\n  valid until %s, sha256 %s"
            % (
                FILES[role],
                "unchanged" if same else "NEW",
                cert.subject.rfc4514_string(),
                cert.not_valid_after_utc.date(),
                fingerprint(cert),
            )
        )
        if args.write and not same:
            with open(path, "wb") as f:
                f.write(pem)
    if changed and not args.write:
        print("\nThe chain differs from the one shipped: run with --write, then update FINGERPRINTS in tests/test_certs.py.")
    return 1 if changed and not args.write else 0


if __name__ == "__main__":
    sys.exit(main())
