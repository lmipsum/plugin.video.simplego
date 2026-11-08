import base64
import calendar
import gzip
import json
import os
import re
import time

import pytest
from providerfakes import AmpHttp
from providerfakes import Answer
from providerfakes import FakeApi
from providerfakes import FakeAuth
from providerfakes import StsHttp
from providerfakes import subscription

from resources.lib import provider
from resources.lib.provider import auth
from resources.lib.provider import channels
from resources.lib.provider import guide as guides
from resources.lib.provider import playback
from resources.lib.provider import statefile
from resources.lib.util import isotime
from resources.lib.util import sharedfile

# A JWT-shaped placeholder, not a real token.
TOKEN = "aaaa.bbbb.cccc"


@pytest.mark.parametrize(
    "text",
    [
        TOKEN,
        "  %s \n" % TOKEN,
        '"%s"' % TOKEN,
        "https://player.telekomtvgo.hu/robots.txt?oauth=x&access_token=AAA&refresh_token=%s&expires_in=5#frag" % TOKEN,
    ],
)
def test_extract_refresh_token(text):
    assert provider.core.extract_refresh_token(text) == TOKEN


@pytest.mark.parametrize("text", ["", None, "hello", "User-agent: *\nDisallow: /", "refresh_token=nodots"])
def test_extract_refresh_token_rejects_text_without_one(text):
    assert provider.core.extract_refresh_token(text) == ""


def test_unwrap_service_certificate():
    cert = bytes(range(200))
    # SignedMessage{type: SERVICE_CERTIFICATE (5), msg: <cert>}; 200 needs a two-byte varint length.
    msg = b"\x08\x05\x12\xc8\x01" + cert
    assert provider.playback.unwrap_service_certificate(msg) == cert


def test_unwrap_service_certificate_rejects_other_messages():
    assert provider.playback.unwrap_service_certificate(b"\x08\x02\x12\x01x") is None
    # Truncated payload.
    assert provider.playback.unwrap_service_certificate(b"\x08\x05\x12\x10abc") is None


def test_account_details_header():
    acc = {
        "account_type": "TYPE",
        "user_id": "1",
        "is_recording_enabled": False,
        "channelMap_id": "2",
        "rightsGroup_ids": "3,4",
        "release_slot": "5",
        "account_id": "1",
        "managed_settings": {"TVSOA-setting-VodEnabled": "true"},
    }
    header = provider.core.account_details(acc)
    assert header == (
        '{"accountType":"TYPE","userId":"1","recordingEnabledDVR":false,"channelMapId":"2",'
        '"rightsGroupIds":"3,4","releaseSlot":"5","accountId":"1","vodEnabled":"true"}'
    )


def _guide(block):
    """A guide whose schedule blocks block(date, offset) gives (what it raises, the provider refused)."""

    def schedule(path, params):
        return {"channels": block(params["date"], int(params["hour_offset"]))}

    return guides.Guide(api=None, auth=FakeAuth(schedule))


def test_epg_stops_at_the_first_day_without_programmes(tmp_path):
    today = int(time.time()) // 86400 * 86400
    published = {time.strftime("%Y-%m-%d", time.gmtime(today + d * 86400)) for d in range(-2, 4)}  # 3 days ahead
    asked = []

    def block(date, offset):
        asked.append(date)
        if date not in published:
            return {}
        start = "%sT%02d:00:00Z" % (date, offset)
        return {"1001": [{"slot_type": "schedule", "start_time": start, "end_time": start}]}

    programmes = _epg(_guide(block), past_days=2, days_ahead=10)
    assert len(programmes["1001"]) == 6 * 8  # two days back, today, three ahead
    assert len(set(asked)) == 7  # the first empty day ends it, not day 10


def test_guest_mode_uses_the_public_channel_list_and_guide(tmp_path):
    calls = []

    def guest_call(path, params):
        calls.append((path, params))
        if path == "/epg/channel":
            return {"channels": [], "serviceCollection_service_map": {}, "services_map": {}}
        return {"channels": {}}

    state = statefile.State(str(tmp_path / "session.json"))  # never logged in
    api = FakeApi(state, guest=guest_call)  # nothing sent with a login: no answers for it
    login = auth.Auth(state, api)
    assert not login.authed
    kept = sharedfile.SharedJson(str(tmp_path / "channels.json"), state.lock)
    channels.Channels(state, api, login, kept).list(scope="subscribed")  # no subscription without a login: the public list
    guides.Guide(api, login).now_and_next()
    assert [p for p, _ in calls] == ["/epg/channel", "/epg/channel/schedules"]
    assert "channelMap_id" not in calls[1][1]
    assert "guest" in json.loads((tmp_path / "channels.json").read_text()) and api.sent == []


def _epg(guide, past_days=1, days_ahead=7, stations=None, cache_dir=None, progress=None):
    """{station_id: [programme, ...]} of the guide's blocks, a programme in two blocks once."""
    out = {}
    for _, _, block in guide.epg_blocks(past_days, days_ahead, stations, cache_dir, progress):
        for station, progs in block.channels().items():
            out.setdefault(station, {}).update((p["start_time"], p) for p in progs)
    return {station: [progs[k] for k in sorted(progs)] for station, progs in out.items()}


def _guide_client():
    """A guide whose every block has a programme on 1001 and 1002; the blocks asked for."""
    asked = []

    def block(date, offset):
        asked.append((date, offset))
        start = "%sT%02d:00:00Z" % (date, offset)
        entry = {"slot_type": "schedule", "start_time": start, "end_time": start, "description": "x", "cta": {"big": 1}}
        return {"1001": [entry], "1002": [dict(entry)]}

    return _guide(block), asked


def test_epg_keeps_blocks_between_calls(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    cache = str(tmp_path / "blocks")
    programmes = _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=cache)
    assert len(asked) == 24 and set(programmes) == {"1001"}
    assert "cta" not in programmes["1001"][0]  # only the fields the export uses
    assert guide.epg_stats == {"fetched": 24, "cached": 0}

    # Right after: all kept. For a channel list kept blocks do not cover, fetched again.
    _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=cache)
    assert len(asked) == 24 and guide.epg_stats["cached"] == 24
    _epg(guide, past_days=1, days_ahead=1, stations={"1001", "1002"}, cache_dir=cache)
    assert len(asked) == 48

    # An hour later: only the blocks that had ended when fetched are still good.
    for name in os.listdir(cache):
        os.utime(os.path.join(cache, name), (0, os.path.getmtime(os.path.join(cache, name)) - 3600))
    asked.clear()
    _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=cache)
    fetched = time.time() - 3600
    ended = lambda date, hour: calendar.timegm(time.strptime(date, "%Y-%m-%d")) + (hour + 3) * 3600 <= fetched  # noqa: E731
    assert asked and not any(ended(date, hour) for date, hour in asked)

    # A shorter range drops the blocks it no longer covers.
    _epg(guide, past_days=0, days_ahead=1, stations={"1001"}, cache_dir=cache)
    assert len(os.listdir(cache)) == 16


def test_blocks_days_ahead_are_fetched_again_less_often(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    cache = str(tmp_path / "blocks")
    _epg(guide, past_days=0, days_ahead=4, stations={"1001"}, cache_dir=cache)
    # An hour later: the blocks of today and the next two days are fetched again, the later ones kept.
    for name in os.listdir(cache):
        os.utime(os.path.join(cache, name), (0, os.path.getmtime(os.path.join(cache, name)) - 3600))
    asked.clear()
    _epg(guide, past_days=0, days_ahead=4, stations={"1001"}, cache_dir=cache)
    starts = [calendar_start(date, hour) for date, hour in asked]
    assert asked and max(starts) - time.time() <= provider.guideblocks.NEAR
    assert guide.epg_stats["cached"] >= 16  # days 3 and 4 at least


def calendar_start(date, hour):
    return calendar.timegm(time.strptime(date, "%Y-%m-%d")) + hour * 3600


def test_epg_progress_can_stop_it(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    seen = []

    def progress(done, total):
        seen.append((done, total))
        if done == 3:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _epg(guide, past_days=1, days_ahead=1, progress=progress)
    assert seen == [(1, 24), (2, 24), (3, 24)]


def _playback(tmp_path, roll=None, subscribed=None):
    """A playback on the AMP gateway's fake (see AmpHttp), a login and this subscription."""
    state = statefile.State(str(tmp_path / "session.json"))
    state["device_uuid"] = "u"
    http = AmpHttp(roll or (lambda body: {"cdns": {"cdn": [{"base_uri": "https://cdn/sdash/"}]}, "manifest_uri": MANIFEST}))
    api = FakeApi(state, http)
    return playback.Playback(state, api, FakeAuth(), subscription(subscribed)), http, api


MANIFEST = "LIVE$11/index.mpd/Manifest?device=d&start=LIVE&end=END"


def test_play_live_refuses_channels_outside_the_subscription(tmp_path):
    # The kept subscription list, however old: a channel start does not fetch it again.
    plays, http, api = _playback(tmp_path, subscribed={"11"})
    with pytest.raises(provider.errors.NotSubscribedError):
        plays.play_live({"id": "99", "media_id": "LIVE$99"})
    assert api.bootstraps == [] and http.rolls == []  # no stream session for it


def test_play_live_turns_the_servers_not_in_service_into_not_subscribed(tmp_path):
    # 3097, "channel not in service or channel not found"; the list unknown, so the server decided.
    plays, _, _ = _playback(tmp_path, roll=lambda body: 3097)
    with pytest.raises(provider.errors.NotSubscribedError):
        plays.play_live({"id": "1417", "media_id": "LIVE$530"})


def test_play_live_restarts_or_plays_back_a_programme(tmp_path):
    plays, http, _ = _playback(tmp_path)
    rolls = http.rolls
    channel = {"id": "11", "media_id": "LIVE$11"}
    now = int(time.time())

    # On air: the live session, its manifest from the programme's start.
    on_air = {"start": "2026-10-27T05:00:00Z", "end": now + 600, "flags": {"ct"}}
    stream = plays.play_live(channel, on_air)
    assert rolls[-1]["isLive"] is True and "start=2026-10-27T05:00:00Z&end=END" in stream["manifest"]
    assert stream["from_start"]

    # Over: a catch-up session for its start time.
    over = {"start": "2026-10-27T03:00:00Z", "end": now - 600, "flags": {"ct"}}
    stream = plays.play_live(channel, over)
    assert rolls[-1] == {"isLive": False, "rightsMode": "VOD_STREAMING", "startTime": "2026-10-27T03:00:00Z", "inhome": "yes"}
    assert not stream["from_start"]

    count = len(rolls)
    with pytest.raises(provider.errors.RestartNotAllowedError):
        plays.play_live(channel, dict(on_air, flags={"rn"}))
    with pytest.raises(provider.errors.ArchiveUnavailableError):
        plays.play_live(channel, dict(over, flags=set()))
    assert len(rolls) == count  # neither opened a session


def _window(url):
    """Return (start, end) of a manifest URL's query, as Unix times."""
    return tuple(isotime.stamp(re.search(r"\b%s=([^&]+)" % key, url).group(1)) for key in ("start", "end"))


def test_full_hd_asks_the_1080p_profile(tmp_path):
    uri = "LIVE$11/index.mpd/Manifest?device=mgr_live_dash_sd_reach_wv3_v2&start=LIVE&end=END"
    roll = lambda body: {"cdns": {"cdn": [{"base_uri": "https://cdn/sdash/"}]}, "manifest_uri": uri}  # noqa: E731
    plays, _, _ = _playback(tmp_path, roll=roll)
    channel = {"id": "11", "media_id": "LIVE$11"}
    now = time.time()

    # Off: the web profile, nothing to fall back to.
    off = plays.play_live(channel)
    assert "device=mgr_live_dash_sd_reach_wv3_v2&start=LIVE" in off["manifest"] and off["manifest_fallback"] is None
    assert off["window_end"] is None

    # Live: FULL_HD_REWIND back to FULL_HD_HORIZON ahead.
    live = plays.play_live(channel, full_hd=True)
    assert "device=mgr_live_dash_sd_AndroidSTB_wv1_v2" in live["manifest"]
    start, end = _window(live["manifest"])
    assert abs(start - (now - playback.FULL_HD_REWIND)) < 60 and abs(end - (now + playback.FULL_HD_HORIZON)) < 60
    assert abs(live["window_end"] - end) < 1
    assert live["manifest_fallback"] == "https://cdn/sdash/" + uri  # the web one, if this is refused

    # A programme over: its own window.
    over = {"start": "2026-11-08T00:00:00Z", "end": int(now) - 3600, "flags": {"ct"}}
    watched_back = plays.play_live(channel, over, full_hd=True)
    assert _window(watched_back["manifest"]) == (isotime.stamp("2026-11-08T00:00:00Z"), int(now) - 3600)
    assert watched_back["window_end"] is None  # a static manifest: no live window to end

    # On air, from its beginning: its start, and an end ahead.
    on_air = {"start": isotime.iso(now - 1800), "end": int(now) + 1800, "flags": {"ct"}}
    restarted = plays.play_live(channel, on_air, full_hd=True)
    start, end = _window(restarted["manifest"])
    assert start == isotime.stamp(on_air["start"]) and end > now + 3600 and abs(restarted["window_end"] - end) < 1


def test_play_live_turns_2401_into_archive_unavailable(tmp_path):
    plays, _, _ = _playback(tmp_path, roll=lambda body: 2401)
    with pytest.raises(provider.errors.ArchiveUnavailableError):
        plays.play_live({"id": "11", "media_id": "LIVE$11"}, {"start": "2026-10-27T03:00:00Z", "end": 0, "flags": {"ct"}})


def test_an_expired_catch_up_is_said_so_in_its_own_words(tmp_path):
    from resources.lib.service import quickplay

    plays, _, _ = _playback(tmp_path, roll=lambda body: 2425)  # "Expired catchup asset"
    with pytest.raises(provider.errors.CatchupExpiredError) as e:
        plays.play_live({"id": "11", "media_id": "LIVE$11"}, {"start": "2026-10-27T03:00:00Z", "end": 0, "flags": {"ct"}})
    # A dialog in the add-on's words, not the server's code.
    assert e.value.kind in quickplay.ERRORS and isinstance(e.value, provider.errors.ArchiveUnavailableError)


def test_play_live_plays_a_programme_not_on_yet_live(tmp_path):
    plays, http, _ = _playback(tmp_path)
    rolls = http.rolls
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    stream = plays.play_live({"id": "11", "media_id": "LIVE$11"}, {"start": later, "end": time.time() + 7200, "flags": {"ct"}})
    assert rolls[-1]["isLive"] is True and "start=LIVE" in stream["manifest"] and not stream["from_start"]


def test_a_block_that_cannot_be_kept_leaves_no_file_behind(tmp_path, monkeypatch):
    from resources.lib.util import atomicfile

    path = tmp_path / "gone" / ("2026-10-27-15.v%d.json.gz" % provider.guideblocks.BLOCK_VERSION)
    provider.guideblocks.store_block(str(path), None, {"1001": []})  # its folder is missing: fetched again next time
    assert not (tmp_path / "gone").exists()
    path = tmp_path / path.name

    def full_disk(src, dst):
        raise OSError("No space left on device")

    monkeypatch.setattr(atomicfile.os, "replace", full_disk)
    provider.guideblocks.store_block(str(path), None, {"1001": []})
    assert list(tmp_path.iterdir()) == []  # the half-written temp file is gone too


def test_programme_at_reads_a_kept_block_without_a_request(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    # Yesterday's 15:00 block: within the archive, so fetching another block does not drop it.
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    when = calendar.timegm(time.strptime(day + " 17:30", "%Y-%m-%d %H:%M"))
    path = tmp_path / ("%s-15.v%d.json.gz" % (day, provider.guideblocks.BLOCK_VERSION))
    progs = [
        {"start_time": day + "T17:00:00Z", "end_time": day + "T18:00:00Z", "content_flags": ["rn", "ts"]},
        {"start_time": day + "T18:00:00Z", "end_time": day + "T19:00:00Z"},
    ]
    # Kept by the Kodi TV export for its channels only: good for those.
    provider.guideblocks.store_block(str(path), {"1001"}, {"1001": progs})
    programme, end = guide.programme_at("1001", when, str(tmp_path))
    assert programme["content_flags"] == ["rn", "ts"] and end == when + 1800
    assert asked == []
    # A station it was not kept for: the whole block is fetched, and kept for every station.
    assert guide.programme_at("1002", when, str(tmp_path)) == (None, None)  # the fake block's programmes are empty
    assert asked == [(day, 15)]
    with gzip.open(str(path), "rt", encoding="utf-8") as f:
        assert json.loads(f.readline())["stations"] is None


def test_programme_at_fetches_a_missing_block_once(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    blocks = str(tmp_path / "blocks")  # not there yet: Kodi TV never set up
    when = time.time() - 3600
    guide.programme_at("1001", when, blocks)
    guide.programme_at("1002", when, blocks)
    assert len(asked) == 1


def test_programme_at_is_unknown_when_the_guide_cannot_be_had(tmp_path, monkeypatch):
    guide, _ = _guide_client()

    def refused(date, offset):
        raise provider.ApiError("down")

    assert _guide(refused).programme_at("1001", time.time(), str(tmp_path)) == (None, None)


def test_now_and_next_keeps_its_block_for_playback(tmp_path, monkeypatch):
    asked = []
    now = time.time()
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60))
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 600))
    client = _guide(
        lambda d, o: (
            asked.append(o)
            or {
                "1001": [
                    {"slot_type": "schedule", "start_time": start, "end_time": end},
                    {"slot_type": "schedule", "start_time": end, "end_time": end, "description": "Híradó"},
                ]
            }
        ),
    )
    now_on, following = client.now_and_next(str(tmp_path))["1001"]
    assert now_on["end_time"] == end and following["description"] == "Híradó"  # next, from the same block
    assert client.programme_at("1001", now, str(tmp_path))[0]["start_time"] == start
    assert len(asked) == 1  # the channel list's block served the playback


def test_blocks_older_than_the_archive_are_dropped(tmp_path, monkeypatch):
    guide, _ = _guide_client()
    old = tmp_path / ("2026-01-01-00.v%d.json.gz" % provider.guideblocks.BLOCK_VERSION)
    old.write_bytes(b"x")
    guide.programme_at("1001", time.time(), str(tmp_path))
    assert not old.exists()


def test_epg_takes_a_refused_day_beyond_the_guide_for_its_end():
    tomorrow = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400))

    def block(date, offset):
        if date > tomorrow:  # out of the published range: refused, not empty
            e = provider.ApiError("HTTP 400")
            e.status = 400
            raise e
        start = "%sT%02d:00:00Z" % (date, offset)
        return {"1001": [{"slot_type": "schedule", "start_time": start, "end_time": start}]}

    assert len(_epg(_guide(block), past_days=0, days_ahead=13)["1001"]) == 16  # today and tomorrow

    def refused_today(date, offset):
        e = provider.ApiError("HTTP 400")
        e.status = 400
        raise e

    with pytest.raises(provider.ApiError):
        _epg(_guide(refused_today), past_days=0, days_ahead=1)


def test_parental_lock_flag_and_pin_check(tmp_path, monkeypatch):
    client = provider.Client(str(tmp_path))
    calls = []
    answers = {"/setting/account/v2": {"parental_control_enabled": True}, "/setting/passcode/verify/v2": {"status": True}}

    def bifrost(path, flow, step=None, auth=False, params=None, method="GET", readd=True, body=None):
        calls.append((path, method, body))
        return answers[path]

    monkeypatch.setattr(client.auth, "call", bifrost)
    assert client.personal.parental_lock_enabled() and client.personal.parental_lock_enabled()
    assert len(calls) == 1  # kept, not asked again

    # The PIN goes RSA-OAEP encrypted with the startup page's key (here a test key's).
    monkeypatch.setattr(provider.rsaoaep, "encrypt", lambda key, message: base64.b64encode(key.encode() + message).decode())
    client.state["pin_key"] = "KEY"
    assert client.personal.verify_pin("1234")
    path, method, body = calls[-1]
    assert (path, method) == ("/setting/passcode/verify/v2", "POST") and base64.b64decode(body["passcode"]) == b"KEY1234"

    answers["/setting/passcode/verify/v2"] = {"status": False}
    assert not client.personal.verify_pin("0000")


def test_favourite_channels_and_programmes_as_the_web_sends_them(tmp_path, monkeypatch):
    client = provider.Client(str(tmp_path))
    (tmp_path / "channels.json").write_text(json.dumps({"favourite": {"list": []}, "subscribed": {"list": []}}))
    calls = []

    def bifrost(path, flow, step=None, auth=False, params=None, method="GET", readd=True, body=None):
        calls.append((path, flow, step, method, body))
        if path.endswith("/actions/v2"):
            return {"actions": {"catchup_schedules": [{"program_id": "P"}], "schedules": []}}
        return {"items": [{"id": "S1"}]} if path == "/watchlist/v2/items" else {}

    monkeypatch.setattr(client.auth, "call", bifrost)
    client.personal.set_favourite_channel("8", True)
    client.personal.set_favourite_channel(8, False)
    assert calls[0] == ("/epg/channel/favourite", "MY_CHANNELS", "SET_FAVOURITE", "POST", {"add_keys": [8]})
    assert calls[1][4] == {"delete_keys": [8]}
    assert json.loads((tmp_path / "channels.json").read_text()) == {"subscribed": {"list": []}}  # fetched again next time

    assert client.personal.watchlist() == [{"id": "S1"}]
    client.personal.set_watchlist("S1", False)
    removed = {"delete_action": [{"id": "S1", "type": "series"}]}
    assert calls[-1] == ("/watchlist/items", "MY_WATCHLIST", "UPDATE_WATCHLIST", "POST", removed)
    assert client.personal.airings("S1") == ([{"program_id": "P"}], [])
    client.personal.airings("M1", "program")
    assert calls[-1][0] == "/details/program/M1/actions/v2"


def test_the_accounts_channel_order_is_read_as_text_ids_and_kept(tmp_path, monkeypatch):
    client = provider.Client(str(tmp_path))
    calls = []
    monkeypatch.setattr(client.auth, "call", lambda *a, **k: calls.append(a) or {"channel_order": [18593, 18587]})
    assert client.personal.channel_order() == ["18593", "18587"] and client.personal.channel_order() == ["18593", "18587"]
    assert len(calls) == 1


def test_channel_order_is_saved_as_the_web_does(tmp_path, monkeypatch):
    client = provider.Client(str(tmp_path))
    calls = []

    def bifrost(path, flow, step=None, **kw):
        calls.append((path, flow, step, kw.get("body")))
        return {}

    monkeypatch.setattr(client.auth, "call", bifrost)
    client.personal.set_channel_order(["18593", "18587"])
    assert calls[-1] == ("/epg/channel/order", "MY_CHANNELS", "SET_CHANNEL_ORDER", {"channel_order": [18593, 18587]})
    assert client.personal.channel_order() == ["18593", "18587"] and len(calls) == 1  # kept, not fetched again
    client.personal.set_channel_order([])  # the web's reset
    assert calls[-1][3] == {"channel_order": []} and client.personal.channel_order() == []


def test_bookmarks_as_the_web_player_keeps_them(tmp_path, monkeypatch):
    client = provider.Client(str(tmp_path))
    calls = []

    def bifrost(path, flow, step=None, auth=False, params=None, method="GET", readd=True, body=None):
        calls.append((path, flow, step, method, params, body))
        return {"bookmarks": [{"id": "18718_A_B", "time_seconds": 631, "runtime_seconds": 7920}]}

    monkeypatch.setattr(client.auth, "call", bifrost)
    assert client.personal.bookmarks()[0]["time_seconds"] == 631
    assert calls[-1][:5] == ("/details/bookmarks/v3", "START_UP", "BOOKMARK_CATCHUP", "GET", {"type": "CATCHUP"})
    info = {"id": "18718_A_B", "program_id": "P", "media_id": "LIVE$707"}
    info.update(start_time="A", end_time="B", station_id="18718")
    client.personal.set_bookmark(info, 621.4726, 7920.0)
    path, flow, step, method, _, body = calls[-1]
    assert (path, flow, step, method) == ("/details/bookmarks/CATCHUP/v3", "PLAYER", "SET_BOOKMARK", "PUT")
    assert body == dict(info, time_seconds=621.473, runtime_seconds=7920)


def test_a_programme_started_from_the_shown_list_asks_no_positions_again(tmp_path, monkeypatch):
    client = provider.Client(str(tmp_path))
    asked = []

    def bifrost(path, flow, step=None, auth=False, params=None, method="GET", readd=True, body=None):
        asked.append(step)
        shown = [{"id": "a", "bookmark_type": "Catchup"}, {"id": "v", "bookmark_type": "Vod"}]
        return {"bookmarks": shown}

    monkeypatch.setattr(client.auth, "call", bifrost)
    client.personal.bookmarks(details=True)  # the "Continue watching" list
    assert [b["id"] for b in client.personal.bookmarks()] == ["a"] and asked == ["BOOKMARK_ALL"]


def test_saving_keeps_what_other_clients_wrote(tmp_path):
    first, second = provider.Client(str(tmp_path)), provider.Client(str(tmp_path))
    first.state["refresh_token"] = "rotated"
    first.state.save()
    # The second client still holds the file as it was; its own change goes in, the renewal stays.
    second.state["pin_key"] = "KEY"
    second.state.save()
    third = provider.Client(str(tmp_path))
    assert third.state["refresh_token"] == "rotated" and third.state["pin_key"] == "KEY"
    assert second.state["refresh_token"] == "rotated"  # taken up when it saved


def test_saving_drops_only_the_keys_this_client_removed(tmp_path):
    first = provider.Client(str(tmp_path))
    first.state.update(refresh_token="r", account={"a": 1})
    first.state.save()
    second = provider.Client(str(tmp_path))
    first.state["pin_key"] = "KEY"
    first.state.save()
    del second.state["account"]
    second.state.save()
    assert provider.Client(str(tmp_path)).state == {"refresh_token": "r", "pin_key": "KEY"}


def test_a_network_failure_is_an_api_error(tmp_path):
    with pytest.raises(provider.ApiError):
        provider.core.Api(statefile.State(str(tmp_path / "session.json"))).http.get("http://127.0.0.1:1/", timeout=5)


def test_token_expiry():
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1824576516, "typ": "Refresh"}).encode()).decode().rstrip("=")
    assert provider.core.token_expiry("aaaa.%s.cccc" % payload) == 1824576516
    assert provider.core.token_expiry("not a jwt") is None
    assert provider.core.token_expiry(None) is None


def test_lists_browsed_again_are_kept_a_while(tmp_path, monkeypatch):
    client = provider.Client(str(tmp_path))
    asked = []

    def bifrost(path, flow, step=None, auth=False, params=None, method="GET", body=None, readd=True):
        asked.append((method, path))
        back, coming = {"start_utc": "1", "description": "a long plot"}, {"start_utc": "2"}
        actions = {"catchup_schedules": [back], "schedules": [coming]}
        return {"items": [{"id": "s1"}], "bookmarks": [{"id": "b"}], "actions": actions}

    monkeypatch.setattr(client.auth, "call", bifrost)
    for _ in range(2):
        assert client.personal.watchlist() == [{"id": "s1"}]
        # Kept with the fields the plugin uses only (no plots: the state file is read by every call).
        assert client.personal.airings("s1") == ([{"start_utc": "1"}], [{"start_utc": "2"}])
        assert client.personal.bookmarks() == [{"id": "b"}]
    assert len(asked) == 3  # each asked once
    # What the add-on changes itself drops what was kept.
    client.personal.set_watchlist("s1", False)
    client.personal.watchlist()
    client.personal.set_bookmark({"id": "b"}, 10, 100)
    client.personal.bookmarks()
    assert [m for m, _ in asked].count("GET") == 5
    # Later than its time, asked again.
    monkeypatch.setattr(time, "time", lambda: 10**10)
    client.personal.airings("s1")
    assert [m for m, _ in asked].count("GET") == 6


def test_a_lookup_takes_a_kept_block_for_hours_an_export_only_for_minutes(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    now = time.time()
    guide.programme_at("1001", now, str(tmp_path))
    assert len(asked) == 1
    for name in os.listdir(str(tmp_path)):
        path = os.path.join(str(tmp_path), name)
        os.utime(path, (0, os.path.getmtime(path) - 30 * 60))  # half an hour old
    guide.programme_at("1001", now, str(tmp_path))
    assert len(asked) == 1  # still good to look up what is on
    date, offset = time.strftime("%Y-%m-%d", time.gmtime(now)), time.gmtime(now).tm_hour // 3 * 3
    guide.epg_blocks(past_days=0, days_ahead=0, cache_dir=str(tmp_path))
    assert asked.count((date, offset)) == 2  # the export's own freshness: fetched again


def test_getting_ready_ahead_renews_what_runs_out_soon_and_registers_again(tmp_path):
    state = statefile.State(str(tmp_path / "session.json"))
    state.update(device_uuid="u", config_at=time.time() - provider.core.CONFIG_TTL + 600, registered_channel="18718")
    http, login = AmpHttp(), FakeAuth()
    api = FakeApi(state, http)
    plays = playback.Playback(state, api, login, subscription(None))
    plays.get_ready(3600)
    # The startup page fetched again, the token asked for valid an hour ahead, the device registered for it.
    assert api.bootstraps == [True] and login.tokens[0] == 3600 and http.registrations == ["18718"]
    plays.get_ready(3600)
    assert api.bootstraps == [True] and http.registrations == ["18718"]  # nothing due: nothing fetched


def test_kept_blocks_are_read_only_when_their_programmes_are_asked_for(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    cache = str(tmp_path / "blocks")
    first = guide.epg_blocks(past_days=0, days_ahead=1, stations={"1001"}, cache_dir=cache)
    read = []
    original = provider.guideblocks.read_channels
    monkeypatch.setattr(provider.guideblocks, "read_channels", lambda *a: read.append(a) or original(*a))
    again = guide.epg_blocks(past_days=0, days_ahead=1, stations={"1001"}, cache_dir=cache)
    assert len(asked) == 16 and read == []  # each kept block's header only
    assert [b.digest() for _, _, b in again] == [b.digest() for _, _, b in first]  # fetched or kept: the same file
    assert again[0][2].programmes == 1 and again[0][2].channels()["1001"][0]["description"] == "x" and len(read) == 1


def test_a_block_read_again_is_not_parsed_again_until_its_file_changes(tmp_path, monkeypatch):
    path = str(tmp_path / ("2026-10-27-15.v%d.json.gz" % provider.guideblocks.BLOCK_VERSION))
    provider.guideblocks.store_block(path, None, {"1001": [{"start_time": "a"}]})
    parsed = []
    original = provider.guideblocks.json.loads
    monkeypatch.setattr(provider.guideblocks.json, "loads", lambda text: parsed.append(1) or original(text))
    assert provider.guideblocks.read_channels(path, None) == provider.guideblocks.read_channels(path, {"1001"})
    assert len(parsed) == 1
    provider.guideblocks.store_block(path, None, {"1001": [{"start_time": "b"}]})
    os.utime(path, ns=(0, os.stat(path).st_mtime_ns + 10**9))  # fetched again
    assert provider.guideblocks.read_channels(path, None)["1001"][0]["start_time"] == "b" and len(parsed) == 2


def test_a_block_already_over_is_looked_up_however_old(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    earlier = time.time() - 6 * 3600  # a programme watched back from the TV menu's guide
    guide.programme_at("1001", earlier, str(tmp_path))
    assert len(asked) == 1
    for name in os.listdir(str(tmp_path)):
        path = os.path.join(str(tmp_path), name)
        os.utime(path, (0, earlier - 3600))  # fetched before it was on: out of date for what is on now
    guide.programme_at("1001", earlier, str(tmp_path))
    assert len(asked) == 1  # it is over: kept as it is
    guide.programme_at("1001", time.time(), str(tmp_path))
    assert len(asked) == 2  # the block on now is another one


def test_taking_up_others_changes_writes_nothing(tmp_path):
    first, second = provider.Client(str(tmp_path)), provider.Client(str(tmp_path))
    first.state["refresh_token"] = "rotated"
    first.state.save()
    written = os.stat(str(tmp_path / "session.json")).st_mtime_ns
    os.utime(str(tmp_path / "session.json"), ns=(written - 10**9, written - 10**9))
    second.state.save()
    assert second.state["refresh_token"] == "rotated"
    assert os.stat(str(tmp_path / "session.json")).st_mtime_ns == written - 10**9  # read, not written again


def test_the_device_profile_is_sent_and_registered_with(tmp_path, monkeypatch):
    plays, http, _ = _playback(tmp_path)
    profile = json.loads(base64.b64decode(plays.licence_headers("11")["DeviceProfile"]))
    assert profile == dict(provider.playback.DEVICE_PROFILE, deviceUUID="u")
    channel = {"id": "11", "media_id": "LIVE$11"}
    plays.play_live(channel)
    plays.play_live(channel)
    assert http.registrations == ["11"]  # once per token and profile
    monkeypatch.setattr(provider.playback, "DEVICE_PROFILE", dict(profile, wvLevel="L1"))
    plays.play_live(channel)
    assert http.registrations == ["11", "11"]  # another profile: registered again with it


def test_continue_watching_positions_are_deleted_as_the_web_edit_mode_sends_them(tmp_path, monkeypatch):
    client = provider.Client(str(tmp_path))
    client.state["kept"] = {"bookmarks:": {"at": 9e9, "data": []}}
    calls = []
    monkeypatch.setattr(client.auth, "call", lambda path, flow, step=None, **kw: calls.append((path, kw)) or {})
    mark = {"id": "1_a_b", "runtime_seconds": 60, "program_id": "P", "bookmark_type": "Catchup", "subject_id": "S", "title": "x"}
    client.personal.delete_bookmarks([mark])
    ((path, kw),) = calls
    assert path == "/delete/bookmarks/v2" and kw["method"] == "POST"
    assert kw["body"] == {
        "bookmarks": [{k: mark[k] for k in ("id", "runtime_seconds", "program_id", "bookmark_type", "subject_id")}]
    }
    assert "bookmarks:" not in client.state["kept"]  # the list is fetched again


def _login(tmp_path, answers):
    """A logged-in Auth whose bifrost answers these responses in turn; the API and the STS it uses."""
    state = statefile.State(str(tmp_path / "session.json"))
    state.update(refresh_token="r", access_token="t", access_expires=time.time() + 3600)
    sts = StsHttp()
    tenant = {"refresh_login_url": "https://sts.example/refresh?token=${refreshToken}&to=${redirectUri}"}
    api = FakeApi(state, sts, answers, guest=lambda path, params: tenant)
    return auth.Auth(state, api), api, sts


def test_a_refused_token_is_renewed_and_the_call_made_again(tmp_path):
    login, api, sts = _login(tmp_path, [Answer(401), Answer(data={"ok": True})])
    assert login.call("/x", "F") == {"ok": True}
    assert [path for path, _ in api.sent] == ["/x", "/x"] and sts.renewals == 1
    assert login.valid_access_token() == "new"
    login, api, sts = _login(tmp_path / "again", [Answer(401), Answer(401)])
    with pytest.raises(provider.AuthError):
        login.call("/x", "F")  # refused even so: no third try
    assert sts.renewals == 1


def test_a_removed_device_is_attached_again_once_and_what_was_its_forgotten(tmp_path):
    removed = Answer(401, text="This device was removed")
    account = Answer(data={"channelMap_id": "7"})
    login, api, _ = _login(tmp_path, [removed, account, Answer(data={"ok": True})])
    forgotten = []
    login.on_device_readded(lambda: forgotten.append("registration"))
    assert login.call("/x", "F") == {"ok": True}
    assert api.sent == [("/x", None), ("/user/account", {"fresh_login": "true"}), ("/x", None)]
    assert forgotten == ["registration"]
    # The attaching call itself refused (fresh_login), or a call that must not attach: given up.
    login, api, _ = _login(tmp_path / "attach", [removed])
    with pytest.raises(provider.AuthError):
        login.call("/user/account", "F", params={"fresh_login": "true"})
    login, api, _ = _login(tmp_path / "remove", [removed])
    with pytest.raises(provider.AuthError):
        login.call("/setting/devices/d", "F", method="DELETE", readd=False)
    assert [path for path, _ in api.sent] == ["/setting/devices/d"]


def test_full_hd_leaves_a_manifest_without_a_device_profile_as_it_is():
    url = "https://cdn/LIVE$1/index.mpd/Manifest?start=LIVE"
    assert playback._ask_full_hd(url, None) == (url, None)
