"""Kodi plumbing: settings, JSON-RPC, Kodi's own strings."""

import pytest

from resources.lib import kodiutil


def test_a_jsonrpc_error_reads_as_no_answer(kodi):
    assert kodiutil.kodi_setting("locale.audiolanguage", "default") == "default"


def test_a_jsonrpc_answer_gives_the_settings_value(kodi):
    kodi.JSONRPC["Settings.GetSettingValue"] = {"value": "original"}
    assert kodiutil.kodi_setting("locale.audiolanguage") == "original"


@pytest.fixture
def written(kodi, monkeypatch):
    """The settings written, as (key, value)."""
    import xbmcaddon

    writes = []
    monkeypatch.setattr(xbmcaddon.Addon, "setSettingBool", lambda self, key, value: writes.append((key, value)), raising=False)
    monkeypatch.setattr(xbmcaddon.Addon, "setSettingInt", lambda self, key, value: writes.append((key, value)), raising=False)
    monkeypatch.setattr(kodiutil, "addon", xbmcaddon.Addon)
    return writes


def test_a_setting_set_to_its_value_is_not_written(written):
    import xbmcaddon

    kodiutil.set_setting("parental_adult", xbmcaddon.Addon().getSettingBool("parental_adult"))
    kodiutil.set_setting("parental_age", xbmcaddon.Addon().getSettingInt("parental_age"))
    assert written == []  # each write would be a settings change to the service


def test_a_changed_setting_is_written(written):
    import xbmcaddon

    kodiutil.set_setting("parental_adult", not xbmcaddon.Addon().getSettingBool("parental_adult"))
    assert len(written) == 1


def test_kodis_strings_are_asked_once_per_call(kodi, monkeypatch):
    import xbmc

    asked = []
    monkeypatch.setattr(kodiutil, "_KODI_STRINGS", {})
    monkeypatch.setattr(xbmc, "getLocalizedString", lambda i: asked.append(i) or "Next", raising=False)
    for _ in range(70):  # a channel list's rows
        kodiutil.kodi_string(19031)
    assert asked == [19031]


def test_a_link_opens_in_the_default_browser(kodi):
    kodiutil.open_in_browser("http://127.0.0.1:47913/?c=abc")
    # No package: Android picks the default app for the address.
    assert ('StartAndroidActivity("","android.intent.action.VIEW","","http://127.0.0.1:47913/?c=abc")', "builtin") in kodi.LOG
