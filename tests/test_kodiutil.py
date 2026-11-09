"""Kodi plumbing: settings, JSON-RPC, region formats, Kodi's own strings."""

import time

from resources.lib import kodiutil


def test_jsonrpc_errors_read_as_no_answer(kodi):
    assert kodiutil.kodi_setting("locale.audiolanguage", "default") == "default"
    kodi.JSONRPC["Settings.GetSettingValue"] = {"value": "original"}
    assert kodiutil.kodi_setting("locale.audiolanguage") == "original"


def test_settings_are_written_only_when_they_change(monkeypatch):
    import xbmcaddon

    written = []
    monkeypatch.setattr(xbmcaddon.Addon, "setSettingBool", lambda self, key, value: written.append((key, value)), raising=False)
    monkeypatch.setattr(xbmcaddon.Addon, "setSettingInt", lambda self, key, value: written.append((key, value)), raising=False)
    monkeypatch.setattr(kodiutil, "addon", xbmcaddon.Addon)
    kodiutil.set_setting("parental_adult", xbmcaddon.Addon().getSettingBool("parental_adult"))
    kodiutil.set_setting("parental_age", xbmcaddon.Addon().getSettingInt("parental_age"))
    assert written == []  # each write would be a settings change to the service
    kodiutil.set_setting("parental_adult", not xbmcaddon.Addon().getSettingBool("parental_adult"))
    assert len(written) == 1


def test_kodis_formats_and_strings_are_asked_once_per_call(kodi, monkeypatch):
    import xbmc

    asked = []
    monkeypatch.setattr(kodiutil, "_REGION", {})
    monkeypatch.setattr(kodiutil, "_KODI_STRINGS", {})
    monkeypatch.setattr(xbmc, "getRegion", lambda what: asked.append(what) or "%H:%M:%S", raising=False)
    monkeypatch.setattr(xbmc, "getLocalizedString", lambda i: asked.append(i) or "Next", raising=False)
    for _ in range(70):  # a channel list's rows
        kodiutil.local_time("2026-10-30T20:00:00Z", date=False)
        kodiutil.kodi_string(19031)
    assert asked == ["time", 19031]


def test_dates_follow_kodis_region_formats_with_its_own_day_and_month_names(kodi, monkeypatch):
    kodiutil._REGION.clear()
    formats = {"dateshort": "%Y.%m.%d.", "datelong": "%Y. %B %d., %A", "time": "%H:%M:%S"}
    names = {12: "kedd", 30: "október"}  # Tuesday, October
    monkeypatch.setattr(kodi.xbmc, "getRegion", lambda what: formats[what])
    monkeypatch.setattr(kodiutil, "kodi_string", lambda string_id: names.get(string_id, "?"))
    stamp = time.mktime((2026, 10, 27, 23, 30, 0, 0, 0, -1))
    assert kodiutil.local_date(stamp) == "2026.10.27."
    assert kodiutil.local_clock(stamp) == "23:30"
    # Kodi's names, and its numbers without the leading zero ("%-d", "%#d" on Windows): Android's
    # strftime would print "-d" as it is.
    kodiutil._REGION.clear()
    formats.update(dateshort="%Y. %B %-d., %A", time="%-H:%M")
    early = time.mktime((2026, 10, 5, 7, 5, 0, 0, 0, -1))
    assert kodiutil.local_date(early).endswith(" október 5., ?")  # the 5th is a Monday: "?" in this test
    assert kodiutil.local_clock(early) == "7:05"
    formats["dateshort"] = "%#m/%#d/%Y %%d"
    kodiutil._REGION.clear()
    assert kodiutil.local_date(early) == "10/5/2026 %d"  # an escaped "%%d" stays as it is
    kodiutil._REGION.clear()


def test_a_link_opens_in_the_default_browser(kodi):
    kodiutil.open_in_browser("http://127.0.0.1:47913/?c=abc")
    # No package: Android picks the default app for the address.
    assert ('StartAndroidActivity("","android.intent.action.VIEW","","http://127.0.0.1:47913/?c=abc")', "builtin") in kodi.LOG
