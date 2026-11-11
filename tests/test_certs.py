"""The certificates shipped for the provider's host (see clientfactory.ca_bundle): the chain they complete."""

import glob
import hashlib
import json
import os
import re
import warnings

import certifi
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.utils import CryptographyDeprecationWarning

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "resources", "certs")
# What scripts/update_certs.py fetched and checked; a new chain changes these on purpose.
with open(os.path.join(ROOT, "tests", "cert_fingerprints.json"), encoding="utf-8") as _f:
    FINGERPRINTS = json.load(_f)


def load(name):
    with open(os.path.join(CERTS, name), "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def certifi_roots():
    with open(certifi.where(), "rb") as f:
        pems = re.findall(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", f.read(), re.S)
    with warnings.catch_warnings():
        # An old root in certifi has a serial newer cryptography frowns upon; it is not ours.
        warnings.simplefilter("ignore", CryptographyDeprecationWarning)
        return [x509.load_pem_x509_certificate(pem) for pem in pems]


def test_only_the_known_certificates_are_shipped():
    assert sorted(os.path.basename(p) for p in glob.glob(os.path.join(CERTS, "*.crt"))) == sorted(FINGERPRINTS)


@pytest.mark.parametrize("name", sorted(FINGERPRINTS))
def test_each_certificate_is_the_one_checked(name):
    with open(os.path.join(CERTS, name), "rb") as f:
        der = x509.load_pem_x509_certificate(f.read()).public_bytes(Encoding.DER)
    assert hashlib.sha256(der).hexdigest() == FINGERPRINTS[name]


def kodis_certifi():
    """Skip unless the certifi installed is the one Kodi ships (pinned in requirements-dev.txt)."""
    with open(os.path.join(ROOT, "requirements-dev.txt"), encoding="utf-8") as f:
        pinned = next(line.split("==")[1].strip() for line in f if line.startswith("certifi=="))
    if certifi.__version__ != pinned:
        pytest.skip("certifi %s is not Kodi's (%s)" % (certifi.__version__, pinned))


def test_the_chain_reaches_a_root_kodis_certifi_already_has():
    intermediate, cross_signed = load("intermediate.crt"), load("cross-signed-root.crt")
    # The host's own certificate is issued by the intermediate it fails to send...
    intermediate.verify_directly_issued_by(cross_signed)
    # ...whose issuer, the E46 root, Kodi's certifi lacks: its cross-signed
    # copy chains to USERTrust ECC, which that certifi does have.
    roots = [root for root in certifi_roots() if root.subject == cross_signed.issuer]
    assert roots, "the cross-signing root is not in this certifi"
    cross_signed.verify_directly_issued_by(roots[0])
    # Nothing shipped is a root of its own: no trust is added, only the chain completed.
    assert all(load(name).subject != load(name).issuer for name in FINGERPRINTS)


def test_every_distrusted_root_is_one_kodis_certifi_has():
    from resources.lib import clientfactory

    kodis_certifi()
    with open(certifi.where(), encoding="utf-8") as f:
        labels = set(re.findall(r'# Label: "([^"]+)"', f.read()))
    # A name not in Kodi's certifi (a typo) would leave its root in.
    assert set(clientfactory.DISTRUSTED) <= labels
