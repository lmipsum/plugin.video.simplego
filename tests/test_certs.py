"""The certificates shipped for the web player's host (see clientfactory.ca_bundle): the chain they complete."""

import datetime
import glob
import hashlib
import os
import re
import warnings

import certifi
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.utils import CryptographyDeprecationWarning

CERTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "certs")
# What scripts/update_certs.py fetched and checked; a new chain changes these on purpose.
FINGERPRINTS = {
    "intermediate.crt": "873f0ba80e3ac222656dfd04158cc15c2927d42d5d05f01dee4a47eb43a916df",
    "cross-signed-root.crt": "ea6b89ed6907a209ff9188676fb164e7aced894b8996dfbe5ce5bbcc22de4ddd",
}
# Warned of a year ahead: time to ship a new chain.
NOTICE = datetime.timedelta(days=365)


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


@pytest.mark.parametrize("name", sorted(FINGERPRINTS))
def test_no_certificate_runs_out_within_a_year(name):
    assert load(name).not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc) > NOTICE


def test_the_chain_reaches_a_root_kodis_certifi_already_has():
    intermediate, cross_signed = load("intermediate.crt"), load("cross-signed-root.crt")
    # The host's own certificate is issued by the intermediate it fails to send...
    intermediate.verify_directly_issued_by(cross_signed)
    # ...whose issuer, the E46 root, Kodi's certifi (2023.5.7) lacks: its cross-signed
    # copy chains to USERTrust ECC, which that certifi does have.
    roots = [root for root in certifi_roots() if root.subject == cross_signed.issuer]
    assert roots, "the cross-signing root is not in this certifi"
    cross_signed.verify_directly_issued_by(roots[0])
    # Nothing shipped is a root of its own: no trust is added, only the chain completed.
    assert all(load(name).subject != load(name).issuer for name in FINGERPRINTS)


def entry(label):
    return '\n# Issuer: CN=%s\n# Subject: CN=%s\n# Label: "%s"\n-----BEGIN CERTIFICATE-----\nAA\n-----END CERTIFICATE-----\n' % (
        (label,) * 3
    )


def test_the_bundle_leaves_out_the_roots_certifi_dropped_as_untrustworthy(monkeypatch, tmp_path):
    from resources.lib import clientfactory
    from resources.lib import kodiutil

    cacert = tmp_path / "cacert.pem"
    cacert.write_text(
        entry("GlobalSign Root CA") + entry("emSign ECC Root CA - G3") + entry("GLOBALTRUST 2020") + entry("USERTrust")
    )
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "ca-bundle.pem").write_text("old, unfiltered")
    monkeypatch.setattr(clientfactory, "_certifi_file", lambda: str(cacert))
    monkeypatch.setattr(clientfactory, "_bundle", None)
    monkeypatch.setattr(kodiutil, "PROFILE", str(profile))
    bundle = open(clientfactory.ca_bundle()).read()
    assert '"GlobalSign Root CA"' in bundle and '"USERTrust"' in bundle
    assert "emSign" not in bundle and "GLOBALTRUST" not in bundle
    assert bundle.count("BEGIN CERTIFICATE") == 2 + len(glob.glob(os.path.join(CERTS, "*.crt")))
    assert not (profile / "ca-bundle.pem").exists()  # made without the filter: gone


def test_every_distrusted_root_is_one_kodis_certifi_has():
    from resources.lib import clientfactory

    with open(certifi.where(), encoding="utf-8") as f:
        labels = set(re.findall(r'# Label: "([^"]+)"', f.read()))
    # The pinned certifi is Kodi's: a name not in it (a typo) would leave its root in.
    assert certifi.__version__ != "2023.5.7" or set(clientfactory.DISTRUSTED) <= labels
