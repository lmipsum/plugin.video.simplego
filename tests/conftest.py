import os
import sys

import pytest

# The add-on's modules import each other as resources.lib.*, from the add-on's folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kodistub  # noqa: E402

# Kodi's own modules, stood in for (see kodistub): the add-on's Kodi side imports them.
kodistub.install()


@pytest.fixture
def kodi():
    """Kodi as a test sees it: empty settings, properties and answers, then the test's own."""
    kodistub.reset()
    yield kodistub
    kodistub.reset()


@pytest.fixture
def lock_settings(kodi):
    from resources.lib import parental

    if os.path.exists(parental.FILE):
        os.remove(parental.FILE)
    parental._unlocked.clear()
    yield parental
    if os.path.exists(parental.FILE):
        os.remove(parental.FILE)
