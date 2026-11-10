"""The guide: its blocks fetched or kept for an export, the programme at a time looked up, what is on now and next."""

import calendar
import gzip
import json
import os
import time

import pytest
from providerfakes import FakeApi
from providerfakes import FakeAuth

from resources.lib import provider
from resources.lib.provider import auth
from resources.lib.provider import core
from resources.lib.provider import guide as guides
from resources.lib.provider import guideblocks
from resources.lib.provider import statefile

BLOCKS_PER_DAY = len(guideblocks.BLOCK_OFFSETS)
# An export from yesterday to tomorrow.
THREE_DAYS = 3 * BLOCKS_PER_DAY
HOUR = 3600


def _guide(block):
    """A guide whose schedule blocks block(date, offset) gives (what it raises, the provider refused)."""

    def schedule(path, params):
        return {"channels": block(params["date"], int(params["hour_offset"]))}

    return guides.Guide(api=None, auth=FakeAuth(schedule))


def _epg(guide, past_days=1, days_ahead=7, stations=None, cache_dir=None, progress=None):
    """({station_id: [programme, ...]} of the guide's blocks, a programme in two blocks once; the block counts)."""
    out = {}
    blocks, counts = guide.epg_blocks(past_days, days_ahead, stations, cache_dir, progress)
    for _, _, block in blocks:
        for station, progs in block.channels().items():
            out.setdefault(station, {}).update((p["start_time"], p) for p in progs)
    return {station: [progs[k] for k in sorted(progs)] for station, progs in out.items()}, counts


def _guide_client():
    """A guide whose every block has a programme on 1001 and 1002; the blocks asked for."""
    asked = []

    def block(date, offset):
        asked.append((date, offset))
        start = "%sT%02d:00:00Z" % (date, offset)
        entry = {"slot_type": "schedule", "start_time": start, "end_time": start, "description": "x", "cta": {"big": 1}}
        return {"1001": [entry], "1002": [dict(entry)]}

    return _guide(block), asked


def _refused(date, offset):
    """A block out of the published range: refused, not empty."""
    e = provider.ApiError("HTTP 400")
    e.status = 400
    raise e


def _day(stamp):
    return time.strftime("%Y-%m-%d", time.gmtime(stamp))


def _block_start(date, offset):
    return calendar.timegm(time.strptime(date, "%Y-%m-%d")) + offset * HOUR


def _age(folder, seconds):
    """Make the kept blocks in folder look fetched this many seconds earlier."""
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        os.utime(path, (0, os.path.getmtime(path) - seconds))


def test_epg_stops_at_the_first_day_without_programmes():
    today = int(time.time()) // guideblocks.DAY_SECONDS * guideblocks.DAY_SECONDS
    published = {_day(today + d * guideblocks.DAY_SECONDS) for d in range(-2, 4)}  # two days back, today, three ahead
    asked = []

    def block(date, offset):
        asked.append(date)
        if date not in published:
            return {}
        start = "%sT%02d:00:00Z" % (date, offset)
        return {"1001": [{"slot_type": "schedule", "start_time": start, "end_time": start}]}

    programmes, _ = _epg(_guide(block), past_days=2, days_ahead=10)
    assert len(programmes["1001"]) == len(published) * BLOCKS_PER_DAY
    assert len(set(asked)) == len(published) + 1  # the first empty day ends it, not day 10


def test_epg_takes_a_refused_day_beyond_the_guide_for_its_end():
    tomorrow = _day(time.time() + guideblocks.DAY_SECONDS)

    def block(date, offset):
        if date > tomorrow:
            return _refused(date, offset)
        start = "%sT%02d:00:00Z" % (date, offset)
        return {"1001": [{"slot_type": "schedule", "start_time": start, "end_time": start}]}

    assert len(_epg(_guide(block), past_days=0, days_ahead=13)[0]["1001"]) == 2 * BLOCKS_PER_DAY  # today and tomorrow


def test_epg_refused_today_is_an_error():
    with pytest.raises(provider.ApiError):
        _epg(_guide(_refused), past_days=0, days_ahead=1)


def test_guest_mode_asks_the_guide_without_a_channel_map(tmp_path):
    calls = []

    def guest_call(path, params):
        calls.append((path, params))
        return {"channels": {}}

    state = statefile.State(str(tmp_path / core.STATE_FILE))  # never logged in
    api = FakeApi(state, guest=guest_call)  # nothing sent with a login: no answers for it
    guides.Guide(api, auth.Auth(state, api)).now_and_next()
    ((path, params),) = calls
    assert path == "/epg/channel/schedules" and "channelMap_id" not in params
    assert api.sent == []


def test_an_epg_fetches_each_block_and_keeps_only_the_fields_the_export_uses(tmp_path):
    guide, asked = _guide_client()
    programmes, counts = _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=str(tmp_path))
    assert len(asked) == THREE_DAYS and set(programmes) == {"1001"}
    assert "cta" not in programmes["1001"][0]
    assert counts == {"fetched": THREE_DAYS, "cached": 0}


def test_an_epg_right_after_another_takes_every_block_kept(tmp_path):
    guide, asked = _guide_client()
    _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=str(tmp_path))
    _, counts = _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=str(tmp_path))
    assert len(asked) == THREE_DAYS and counts["cached"] == THREE_DAYS


def test_an_epg_for_channels_the_kept_blocks_do_not_cover_fetches_them_again(tmp_path):
    guide, asked = _guide_client()
    _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=str(tmp_path))
    _epg(guide, past_days=1, days_ahead=1, stations={"1001", "1002"}, cache_dir=str(tmp_path))
    assert len(asked) == 2 * THREE_DAYS


def test_an_hour_later_only_the_blocks_ended_when_fetched_are_still_good(tmp_path):
    guide, asked = _guide_client()
    _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=str(tmp_path))
    _age(str(tmp_path), HOUR)
    asked.clear()
    _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=str(tmp_path))
    fetched = time.time() - HOUR
    assert asked and not any(_block_start(date, offset) + guideblocks.BLOCK_SECONDS <= fetched for date, offset in asked)


def test_a_shorter_range_drops_the_blocks_it_no_longer_covers(tmp_path):
    guide, _ = _guide_client()
    _epg(guide, past_days=1, days_ahead=1, stations={"1001"}, cache_dir=str(tmp_path))
    _epg(guide, past_days=0, days_ahead=1, stations={"1001"}, cache_dir=str(tmp_path))
    assert len(os.listdir(str(tmp_path))) == 2 * BLOCKS_PER_DAY


def test_blocks_days_ahead_are_fetched_again_less_often(tmp_path):
    guide, asked = _guide_client()
    _epg(guide, past_days=0, days_ahead=4, stations={"1001"}, cache_dir=str(tmp_path))
    # An hour later: the blocks of today and the next two days are fetched again, the later ones kept.
    _age(str(tmp_path), HOUR)
    asked.clear()
    _, counts = _epg(guide, past_days=0, days_ahead=4, stations={"1001"}, cache_dir=str(tmp_path))
    starts = [_block_start(date, offset) for date, offset in asked]
    assert asked and max(starts) - time.time() <= guideblocks.NEAR
    assert counts["cached"] >= 2 * BLOCKS_PER_DAY  # days 3 and 4 at least


def test_epg_progress_can_stop_it():
    guide, _ = _guide_client()
    seen = []
    stop_at = 3

    def progress(done, total):
        seen.append((done, total))
        if done == stop_at:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _epg(guide, past_days=1, days_ahead=1, progress=progress)
    assert seen == [(done, THREE_DAYS) for done in range(1, stop_at + 1)]


def test_kept_blocks_are_read_only_when_their_programmes_are_asked_for(tmp_path, monkeypatch):
    guide, asked = _guide_client()
    cache = str(tmp_path)
    first, _ = guide.epg_blocks(past_days=0, days_ahead=1, stations={"1001"}, cache_dir=cache)
    read = []
    original = guideblocks.read_channels
    monkeypatch.setattr(guideblocks, "read_channels", lambda *a: read.append(a) or original(*a))
    again, _ = guide.epg_blocks(past_days=0, days_ahead=1, stations={"1001"}, cache_dir=cache)
    assert len(asked) == 2 * BLOCKS_PER_DAY and read == []  # each kept block's header only
    assert [b.digest() for _, _, b in again] == [b.digest() for _, _, b in first]  # fetched or kept: the same file
    assert again[0][2].programmes == 1 and again[0][2].channels()["1001"][0]["description"] == "x" and len(read) == 1


def _yesterdays_block(tmp_path):
    """Keep yesterday's 15:00 block for 1001 alone, as the Kodi TV export does; its path, a time in it and its day."""
    # Within the archive, so fetching another block does not drop it.
    day = _day(time.time() - guideblocks.DAY_SECONDS)
    path = guideblocks.block_path(str(tmp_path), day, 15)
    progs = [
        {"start_time": day + "T17:00:00Z", "end_time": day + "T18:00:00Z", "content_flags": ["rn", "ts"]},
        {"start_time": day + "T18:00:00Z", "end_time": day + "T19:00:00Z"},
    ]
    guideblocks.store_block(path, {"1001"}, {"1001": progs})
    return path, calendar.timegm(time.strptime(day + " 17:30", "%Y-%m-%d %H:%M")), day


def test_programme_at_reads_a_block_kept_for_its_station_without_a_request(tmp_path):
    guide, asked = _guide_client()
    _, when, _ = _yesterdays_block(tmp_path)
    programme, end = guide.programme_at("1001", when, str(tmp_path))
    assert programme["content_flags"] == ["rn", "ts"] and end == when + HOUR / 2
    assert asked == []


def test_programme_at_for_a_station_a_block_was_not_kept_for_fetches_it_for_every_station(tmp_path):
    guide, asked = _guide_client()
    path, when, day = _yesterdays_block(tmp_path)
    assert guide.programme_at("1002", when, str(tmp_path)) == (None, None)  # the fake block's programmes are empty
    assert asked == [(day, 15)]
    with gzip.open(path, "rt", encoding="utf-8") as f:
        assert json.loads(f.readline())["stations"] is None


def test_programme_at_fetches_a_missing_block_once(tmp_path):
    guide, asked = _guide_client()
    blocks = str(tmp_path / "blocks")  # not there yet: Kodi TV never set up
    when = time.time() - HOUR
    guide.programme_at("1001", when, blocks)
    guide.programme_at("1002", when, blocks)
    assert len(asked) == 1


def test_programme_at_is_unknown_when_the_guide_cannot_be_had(tmp_path):
    def down(date, offset):
        raise provider.ApiError("down")

    assert _guide(down).programme_at("1001", time.time(), str(tmp_path)) == (None, None)


def test_now_and_next_keeps_its_block_for_playback(tmp_path):
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
                    {"slot_type": "schedule", "start_time": end, "end_time": end, "description": "Next"},
                ]
            }
        ),
    )
    now_on, following = client.now_and_next(str(tmp_path))["1001"]
    assert now_on["end_time"] == end and following["description"] == "Next"  # next, from the same block
    assert client.programme_at("1001", now, str(tmp_path))[0]["start_time"] == start
    assert len(asked) == 1  # the channel list's block served the playback


def test_blocks_older_than_the_archive_are_dropped(tmp_path):
    guide, _ = _guide_client()
    old = guideblocks.block_path(str(tmp_path), "2026-01-01", 0)
    with open(old, "wb") as f:
        f.write(b"x")
    guide.programme_at("1001", time.time(), str(tmp_path))
    assert not os.path.exists(old)


def _lookup_now_then_age_half_an_hour(tmp_path):
    """A guide whose block on now was looked up half an hour ago; the blocks asked for and that block's (date, offset)."""
    guide, asked = _guide_client()
    now = time.time()
    guide.programme_at("1001", now, str(tmp_path))
    assert len(asked) == 1
    _age(str(tmp_path), HOUR / 2)
    offset = time.gmtime(now).tm_hour // guideblocks.BLOCK_HOURS * guideblocks.BLOCK_HOURS
    return guide, asked, now, (_day(now), offset)


def test_a_lookup_takes_a_kept_block_for_hours(tmp_path):
    guide, asked, now, _ = _lookup_now_then_age_half_an_hour(tmp_path)
    guide.programme_at("1001", now, str(tmp_path))
    assert len(asked) == 1  # still good to look up what is on


def test_an_export_takes_a_kept_block_only_for_minutes(tmp_path):
    guide, asked, _, block = _lookup_now_then_age_half_an_hour(tmp_path)
    guide.epg_blocks(past_days=0, days_ahead=0, cache_dir=str(tmp_path))
    assert asked.count(block) == 2  # the export's own freshness: fetched again


def test_a_block_already_over_is_looked_up_however_old(tmp_path):
    guide, asked = _guide_client()
    earlier = time.time() - 6 * HOUR  # a programme watched back from the TV menu's guide
    guide.programme_at("1001", earlier, str(tmp_path))
    assert len(asked) == 1
    for name in os.listdir(str(tmp_path)):
        os.utime(os.path.join(str(tmp_path), name), (0, earlier - HOUR))  # fetched before it was on: out of date for now
    guide.programme_at("1001", earlier, str(tmp_path))
    assert len(asked) == 1  # it is over: kept as it is
    guide.programme_at("1001", time.time(), str(tmp_path))
    assert len(asked) == 2  # the block on now is another one


def test_an_export_may_hold_each_block_before_it_is_fetched():
    guide = _guide(lambda date, offset: {})
    paused = []
    guide.epg_blocks(past_days=0, days_ahead=0, pause=lambda: paused.append(1))
    assert len(paused) == BLOCKS_PER_DAY
