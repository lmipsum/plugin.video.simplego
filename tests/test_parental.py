"""The parental lock: what it locks and when it asks for the PIN."""

import pytest
from kodiside import Client

from resources.lib import kodiutil
from resources.lib import parental
from resources.lib import provider
from resources.lib.data import guidedata


def test_the_lock_starts_with_no_age_limit_and_unrated_and_adult_locked(lock_settings):
    assert parental.settings() == {"age": 0, "unrated": True, "adult": False}
    assert not parental.locked(16)
    assert parental.locked(None)
    assert parental.locked(0, adult=True)


def test_an_age_limit_locks_that_age_and_above(lock_settings):
    parental.save({"age": 16, "unrated": False, "adult": True})
    assert kodiutil.addon().getSettingInt("parental_age") == 16  # the settings' read-only row follows
    assert not parental.locked(12) and parental.locked(16) and parental.locked(guidedata.ADULT_AGE)
    assert not parental.locked(None) and not parental.locked(12, adult=True)


def test_a_locked_programme_asks_for_the_pin_once(lock_settings, kodi):
    parental.save({"age": 12, "unrated": True, "adult": False})
    client = Client()
    kodi.ANSWERS["numeric"] = "1234"
    programme = {"start": "2026-10-27T20:00:00Z", "age": 16}
    assert parental.gate(client, {"id": "1"}, programme) == programme["start"]
    assert client.pins_checked == ["1234"]
    # Played again soon (a restart at a key change): no second question.
    assert parental.gate(client, {"id": "1"}, programme) == programme["start"]
    assert client.pins_checked == ["1234"]


def test_a_wrong_pin_keeps_the_programme_locked(lock_settings, kodi):
    parental.save({"age": 12, "unrated": True, "adult": False})
    kodi.ANSWERS["numeric"] = "9999"
    with pytest.raises(provider.ParentalLockError):
        parental.gate(Client(), {"id": "1"}, {"start": "2026-10-27T20:00:00Z", "age": 16})
    assert any(kind == "ok" for _, kind in kodi.LOG)  # it says so


def test_an_account_without_a_lock_asks_for_nothing(lock_settings, kodi):
    client = Client(lock=False)
    assert parental.gate(client, {"id": "9"}, {"start": "2026-10-27T20:00:00Z", "age": 19}) is None
    assert client.pins_checked == []


def test_adult_channels_are_hidden_only_where_the_lock_says_so(lock_settings):
    assert parental.hides_adult(Client())
    parental.save({"age": 0, "unrated": True, "adult": True})
    assert not parental.hides_adult(Client())
    assert not parental.hides_adult(Client(lock=False))
