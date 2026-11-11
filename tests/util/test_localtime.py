"""Local dates and times in Kodi's region formats and with its own names."""

import time

import pytest

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


@pytest.fixture
def region(kodi, monkeypatch):
    """Kodi's region formats, by name, for a test to change; Hungarian day and month names, "?" for the rest."""
    formats = {"dateshort": "%Y.%m.%d.", "datelong": "%Y. %B %d., %A", "time": "%H:%M:%S"}
    names = {12: "kedd", 30: "október"}  # Tuesday, October
    monkeypatch.setattr(localtime, "_REGION", {})
    monkeypatch.setattr(kodi.xbmc, "getRegion", lambda what: formats[what])
    monkeypatch.setattr(kodiutil, "kodi_string", lambda string_id: names.get(string_id, "?"))
    return formats


# A Monday, early in the day: numbers with a leading zero.
EARLY = time.mktime((2026, 10, 5, 7, 5, 0, 0, 0, -1))


def test_dates_and_clocks_follow_kodis_region_formats(region):
    stamp = time.mktime((2026, 10, 27, 23, 30, 0, 0, 0, -1))
    assert localtime.local_date(stamp) == "2026.10.27."
    assert localtime.local_clock(stamp) == "23:30"


def test_dates_take_kodis_day_and_month_names_and_its_numbers_without_a_leading_zero(region):
    # "%-d" ("%#d" on Windows): Android's strftime would print "-d" as it is.
    region.update(dateshort="%Y. %B %-d., %A", time="%-H:%M")
    assert localtime.local_date(EARLY).endswith(" október 5., ?")  # Monday's name: "?" in this test
    assert localtime.local_clock(EARLY) == "7:05"


def test_an_escaped_percent_in_a_date_format_stays_as_it_is(region):
    region["dateshort"] = "%#m/%#d/%Y %%d"
    assert localtime.local_date(EARLY) == "10/5/2026 %d"
