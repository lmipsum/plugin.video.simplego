"""The client's CA bundle: certifi's roots, less the distrusted ones, plus the shipped chain."""

import glob
import os

CERTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "certs")


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
