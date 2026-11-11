"""Playback: a channel's stream session, live, from a programme's start or watched back, in Full HD or not."""

import base64
import json
import re
import time

import pytest
from providerfakes import AmpHttp
from providerfakes import FakeApi
from providerfakes import FakeAuth
from providerfakes import subscription

from resources.lib import provider
from resources.lib.provider import core
from resources.lib.provider import playback
from resources.lib.provider import statefile
from resources.lib.util import isotime

BASE_URI = "https://cdn/sdash/"
MANIFEST = "LIVE$11/index.mpd/Manifest?device=mgr_live_dash_sd_reach_wv3_v2&start=LIVE&end=END"
CHANNEL = {"id": "11", "media_id": "LIVE$11"}
OVER_LONG_AGO = {"start": "2026-10-27T03:00:00Z", "end": 0, "flags": {"ct"}}
TEN_MINUTES = 600
HOUR = 3600
# A manifest window's ends and the times around them are compared to the second, within this slack.
CLOCK_SLACK = 60


def _session(body):
    return {"cdns": {"cdn": [{"base_uri": BASE_URI}]}, "manifest_uri": MANIFEST}


def _playback(tmp_path, roll=_session, subscribed=None):
    """A playback on the stream gateway's fake (see AmpHttp), a login and this subscription."""
    state = statefile.State(str(tmp_path / core.STATE_FILE))
    state["device_uuid"] = "u"
    http = AmpHttp(roll)
    api = FakeApi(state, http)
    return playback.Playback(state, api, FakeAuth(), subscription(subscribed)), http, api


def _window(url):
    """Return (start, end) of a manifest URL's query, as Unix times."""
    return tuple(isotime.stamp(re.search(r"\b%s=([^&]+)" % key, url).group(1)) for key in ("start", "end"))


def _on_air(now):
    return {"start": "2026-10-27T05:00:00Z", "end": now + TEN_MINUTES, "flags": {"ct"}}


def _over(now):
    return {"start": "2026-10-27T03:00:00Z", "end": now - TEN_MINUTES, "flags": {"ct"}}


def test_play_live_refuses_channels_outside_the_subscription(tmp_path):
    # The kept subscription list, however old: a channel start does not fetch it again.
    plays, http, api = _playback(tmp_path, subscribed={"11"})
    with pytest.raises(provider.errors.NotSubscribedError):
        plays.play_live({"id": "99", "media_id": "LIVE$99"})
    assert api.bootstraps == [] and http.rolls == []  # no stream session for it


def test_play_live_takes_the_servers_refusal_for_not_subscribed(tmp_path):
    # The subscription unknown: the server decided.
    plays, _, _ = _playback(tmp_path, roll=lambda body: playback.CODE_NOT_SUBSCRIBED)
    with pytest.raises(provider.errors.NotSubscribedError):
        plays.play_live({"id": "1417", "media_id": "LIVE$530"})


def test_a_programme_on_air_restarts_from_its_start(tmp_path):
    plays, http, _ = _playback(tmp_path)
    stream = plays.play_live(CHANNEL, _on_air(int(time.time())))
    assert http.rolls[-1]["isLive"] is True and "start=2026-10-27T05:00:00Z&end=END" in stream["manifest"]
    assert stream["from_start"]


def test_a_programme_over_plays_back_from_its_start(tmp_path):
    plays, http, _ = _playback(tmp_path)
    stream = plays.play_live(CHANNEL, _over(int(time.time())))
    catch_up = {"isLive": False, "rightsMode": "VOD_STREAMING", "startTime": "2026-10-27T03:00:00Z", "inhome": "yes"}
    assert http.rolls[-1] == catch_up
    assert not stream["from_start"]


def test_a_programme_without_restart_rights_opens_no_session(tmp_path):
    plays, http, _ = _playback(tmp_path)
    with pytest.raises(provider.errors.RestartNotAllowedError):
        plays.play_live(CHANNEL, dict(_on_air(int(time.time())), flags={"rn"}))
    assert http.rolls == []


def test_a_programme_over_outside_the_archive_opens_no_session(tmp_path):
    plays, http, _ = _playback(tmp_path)
    with pytest.raises(provider.errors.ArchiveUnavailableError):
        plays.play_live(CHANNEL, dict(_over(int(time.time())), flags=set()))
    assert http.rolls == []


def test_play_live_plays_a_programme_not_on_yet_live(tmp_path):
    plays, http, _ = _playback(tmp_path)
    later = isotime.iso(time.time() + HOUR)
    stream = plays.play_live(CHANNEL, {"start": later, "end": time.time() + 2 * HOUR, "flags": {"ct"}})
    assert http.rolls[-1]["isLive"] is True and "start=LIVE" in stream["manifest"] and not stream["from_start"]


def test_a_catch_up_refused_by_the_server_is_unavailable(tmp_path):
    plays, _, _ = _playback(tmp_path, roll=lambda body: playback.CODE_NOT_IN_ARCHIVE)
    with pytest.raises(provider.errors.ArchiveUnavailableError):
        plays.play_live(CHANNEL, OVER_LONG_AGO)


def test_an_expired_catch_up_is_said_so_in_its_own_words(tmp_path):
    from resources.lib import playmessages

    plays, _, _ = _playback(tmp_path, roll=lambda body: playback.CODE_CATCHUP_EXPIRED)
    with pytest.raises(provider.errors.CatchupExpiredError) as e:
        plays.play_live(CHANNEL, OVER_LONG_AGO)
    # A dialog in the add-on's words, not the server's code.
    assert e.value.kind in playmessages.ERRORS and isinstance(e.value, provider.errors.ArchiveUnavailableError)


def test_without_full_hd_the_usual_profile_plays_with_nothing_to_fall_back_to(tmp_path):
    plays, _, _ = _playback(tmp_path)
    stream = plays.play_live(CHANNEL)
    assert "device=mgr_live_dash_sd_reach_wv3_v2&start=LIVE" in stream["manifest"] and stream["manifest_fallback"] is None
    assert stream["window_end"] is None


def test_full_hd_live_asks_its_profile_from_the_rewind_to_the_horizon(tmp_path):
    plays, _, _ = _playback(tmp_path)
    now = time.time()
    stream = plays.play_live(CHANNEL, full_hd=True)
    assert "device=mgr_live_dash_sd_%s_v2" % playback.FULL_HD_DEVICE_CLASS in stream["manifest"]
    start, end = _window(stream["manifest"])
    assert abs(start - (now - playback.FULL_HD_REWIND)) < CLOCK_SLACK
    assert abs(end - (now + playback.FULL_HD_HORIZON)) < CLOCK_SLACK
    assert abs(stream["window_end"] - end) < 1
    assert stream["manifest_fallback"] == BASE_URI + MANIFEST  # the usual one, if this is refused


def test_full_hd_for_a_programme_over_asks_its_own_window(tmp_path):
    plays, _, _ = _playback(tmp_path)
    end = int(time.time()) - HOUR
    stream = plays.play_live(CHANNEL, {"start": "2026-11-08T00:00:00Z", "end": end, "flags": {"ct"}}, full_hd=True)
    assert _window(stream["manifest"]) == (isotime.stamp("2026-11-08T00:00:00Z"), end)
    assert stream["window_end"] is None  # a static manifest: no live window to end


def test_full_hd_for_a_programme_on_air_from_its_start_asks_an_end_ahead(tmp_path):
    plays, _, _ = _playback(tmp_path)
    now = time.time()
    on_air = {"start": isotime.iso(now - HOUR / 2), "end": int(now) + HOUR / 2, "flags": {"ct"}}
    stream = plays.play_live(CHANNEL, on_air, full_hd=True)
    start, end = _window(stream["manifest"])
    assert start == isotime.stamp(on_air["start"]) and end > now + HOUR and abs(stream["window_end"] - end) < 1


def test_full_hd_leaves_a_manifest_without_a_device_profile_as_it_is():
    url = "https://cdn/LIVE$1/index.mpd/Manifest?start=LIVE"
    assert playback._ask_full_hd(url, None) == (url, None)


def test_getting_ready_ahead_renews_what_runs_out_soon_and_registers_again(tmp_path):
    state = statefile.State(str(tmp_path / core.STATE_FILE))
    state.update(device_uuid="u", config_at=time.time() - core.CONFIG_TTL + TEN_MINUTES, registered_channel="18718")
    http, login = AmpHttp(), FakeAuth()
    api = FakeApi(state, http)
    plays = playback.Playback(state, api, login, subscription(None))
    plays.get_ready(HOUR)
    # The startup page fetched again, the token asked for valid an hour ahead, the device registered for it.
    assert api.bootstraps == [True] and login.tokens[0] == HOUR and http.registrations == ["18718"]
    plays.get_ready(HOUR)
    assert api.bootstraps == [True] and http.registrations == ["18718"]  # nothing due: nothing fetched


def test_the_device_profile_is_sent_and_registered_with(tmp_path, monkeypatch):
    plays, http, _ = _playback(tmp_path)
    profile = json.loads(base64.b64decode(plays.licence_headers("11")["DeviceProfile"]))
    assert profile == dict(playback.DEVICE_PROFILE, deviceUUID="u")
    plays.play_live(CHANNEL)
    plays.play_live(CHANNEL)
    assert http.registrations == ["11"]  # once per token and profile
    monkeypatch.setattr(playback, "DEVICE_PROFILE", dict(profile, wvLevel="L1"))
    plays.play_live(CHANNEL)
    assert http.registrations == ["11", "11"]  # another profile: registered again with it
