"""The live channel played again after Kodi's sleep (the TV off and on)."""

import types

import pytest

from resources.lib.service import wakeresume


@pytest.fixture
def wake(monkeypatch):
    """A WakeResume whose timer fires at once, with what it plays and whether Kodi plays anything."""
    monkeypatch.setattr(wakeresume.threading, "Timer", lambda delay, f, args: types.SimpleNamespace(start=lambda: f(*args)))
    played = []
    wake = wakeresume.WakeResume(lambda channel, why: played.append((channel, why)), lambda: wake.kodi_plays)
    wake.kodi_plays, wake.played = False, played
    return wake


def test_a_live_channel_stopped_as_kodi_went_to_sleep_plays_again_on_waking_up(wake):
    wake.playing({"id": "c1"})
    wake.stopped()
    wake.on_power("System.OnSleep")
    wake.on_power("System.OnWake")
    assert wake.played == [({"id": "c1"}, "after waking up")]
    wake.on_power("System.OnWake")  # once
    assert len(wake.played) == 1


def test_a_live_channel_stopped_long_before_the_sleep_does_not_play_again(wake, monkeypatch):
    wake.playing({"id": "c1"})
    wake.stopped()
    now = wakeresume.time.time()
    monkeypatch.setattr(wakeresume.time, "time", lambda: now + wakeresume.SLEEP_STOP + 1)
    wake.on_power("System.OnSleep")
    wake.on_power("System.OnWake")
    assert wake.played == []


def test_nothing_plays_again_after_something_else_or_while_kodi_plays_already(wake):
    wake.playing(None)  # a programme watched back: Kodi resumes it itself
    wake.on_power("System.OnSleep")
    wake.on_power("System.OnWake")
    wake.playing({"id": "c1"})
    wake.on_power("System.OnSleep")
    wake.kodi_plays = True
    wake.on_power("System.OnWake")
    assert wake.played == []
