"""Local dates and times in Kodi's region formats and with its own names."""

import time

from resources.lib import kodiutil
from resources.lib.util import localtime


def test_kodis_region_formats_are_asked_once_per_call(kodi, monkeypatch):
    import xbmc

    asked = []
    monkeypatch.setattr(localtime, "_REGION", {})
    monkeypatch.setattr(xbmc, "getRegion", lambda what: asked.append(what) or "%H:%M:%S", raising=False)
    for _ in range(70):  # a channel list's rows
        localtime.local_time("2026-10-30T20:00:00Z", date=False)
    assert asked == ["time"]


def test_dates_follow_kodis_region_formats_with_its_own_day_and_month_names(kodi, monkeypatch):
    monkeypatch.setattr(localtime, "_REGION", {})
    formats = {"dateshort": "%Y.%m.%d.", "datelong": "%Y. %B %d., %A", "time": "%H:%M:%S"}
    names = {12: "kedd", 30: "október"}  # Tuesday, October
    monkeypatch.setattr(kodi.xbmc, "getRegion", lambda what: formats[what])
    monkeypatch.setattr(kodiutil, "kodi_string", lambda string_id: names.get(string_id, "?"))
    stamp = time.mktime((2026, 10, 27, 23, 30, 0, 0, 0, -1))
    assert localtime.local_date(stamp) == "2026.10.27."
    assert localtime.local_clock(stamp) == "23:30"
    # Kodi's names, and its numbers without the leading zero ("%-d", "%#d" on Windows): Android's
    # strftime would print "-d" as it is.
    localtime._REGION.clear()
    formats.update(dateshort="%Y. %B %-d., %A", time="%-H:%M")
    early = time.mktime((2026, 10, 5, 7, 5, 0, 0, 0, -1))
    assert localtime.local_date(early).endswith(" október 5., ?")  # the 5th is a Monday: "?" in this test
    assert localtime.local_clock(early) == "7:05"
    formats["dateshort"] = "%#m/%#d/%Y %%d"
    localtime._REGION.clear()
    assert localtime.local_date(early) == "10/5/2026 %d"  # an escaped "%%d" stays as it is
