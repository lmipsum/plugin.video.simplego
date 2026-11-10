"""The live channel played again after Kodi's sleep (the TV off and on) or a return from another HDMI input."""

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
    wake.stopped(0, next_on_its_way=False)
    wake.on_power("System.OnSleep")
    wake.on_power("System.OnWake")
    assert wake.played == [({"id": "c1"}, "after waking up")]
    wake.on_power("System.OnWake")  # once
    assert len(wake.played) == 1


def test_a_live_channel_stopped_long_before_the_sleep_does_not_play_again(wake, monkeypatch):
    wake.playing({"id": "c1"})
    wake.stopped(0, next_on_its_way=False)
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


def test_a_live_channel_stopped_with_no_key_pressed_plays_again(wake):
    wake.playing({"id": "c1"})
    wake.stopped(wakeresume.RETURN_IDLE, next_on_its_way=False)  # back from another HDMI input
    assert wake.played == [({"id": "c1"}, "after a return")]


@pytest.mark.parametrize(("idle", "next_on_its_way"), [(0, False), (wakeresume.RETURN_IDLE, True)])
def test_a_stop_by_the_user_or_for_another_stream_plays_nothing_again(wake, idle, next_on_its_way):
    wake.playing({"id": "c1"})
    wake.stopped(idle, next_on_its_way)
    assert wake.played == []


def test_a_channel_played_again_that_stops_again_soon_is_not_played_again(wake):
    for _ in range(2):
        wake.playing({"id": "c1"})
        wake.stopped(wakeresume.RETURN_IDLE, next_on_its_way=False)
    assert len(wake.played) == 1


def test_a_second_return_after_the_channel_played_a_while_plays_it_again(wake, monkeypatch):
    wake.playing({"id": "c1"})
    wake.stopped(wakeresume.RETURN_IDLE, next_on_its_way=False)
    wake.playing({"id": "c1"})  # the channel played again
    now = wakeresume.time.time()
    monkeypatch.setattr(wakeresume.time, "time", lambda: now + wakeresume.SHORT_PLAY)
    wake.stopped(wakeresume.RETURN_IDLE, next_on_its_way=False)  # another HDMI input and back
    assert len(wake.played) == 2


def test_something_else_stopped_plays_nothing_again(wake):
    wake.playing(None)
    wake.stopped(wakeresume.RETURN_IDLE, next_on_its_way=False)
    assert wake.played == []
