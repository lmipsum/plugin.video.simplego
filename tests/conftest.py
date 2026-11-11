import os
import sys

import pytest

# The add-on's modules import each other as resources.lib.*, from the add-on's folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kodistub  # noqa: E402

# Kodi's own modules, stood in for (see kodistub): the add-on's Kodi side imports them.
kodistub.install()


@pytest.fixture(autouse=True)
def fresh_kodi(tmp_path_factory, monkeypatch):
    """Start every test with Kodi as new: empty settings, properties and answers, a profile folder of its own."""
    from resources.lib import kodiutil
    from resources.lib import parental
    from resources.lib.data import channellist
    from resources.lib.data import continuelist
    from resources.lib.data import onair

    kodistub.reset()
    profile = str(tmp_path_factory.mktemp("profile"))
    monkeypatch.setattr(kodistub, "PROFILE", profile)
    monkeypatch.setitem(kodistub.Addon.INFO, "profile", profile)
    # These modules join their file's path to the profile when imported.
    for module, name in ((parental, "FILE"), (continuelist, "KEPT"), (channellist, "DEACTIVATED"), (onair, "BLOCKS")):
        monkeypatch.setattr(module, name, os.path.join(profile, os.path.relpath(getattr(module, name), kodiutil.PROFILE)))
    monkeypatch.setattr(kodiutil, "PROFILE", profile)
    yield
    kodistub.reset()


@pytest.fixture
def kodi():
    """Kodi as a test sees it (see kodistub)."""
    return kodistub


@pytest.fixture
def lock_settings(kodi):
    from resources.lib import parental

    parental._unlocked.clear()
    return parental
