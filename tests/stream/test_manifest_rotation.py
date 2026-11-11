"""The manifest rewriter under key rotation: init segments name one key pair, the fragments another.

A live stream follows its newest fragments' keys; a catch-up takes the keys it starts with and,
across a key change, plays in parts.
"""

import re
import xml.etree.ElementTree as ET

from dashfakes import BASE
from dashfakes import CENC
from dashfakes import KID
from dashfakes import MPD_TAG
from dashfakes import MPD_URL
from dashfakes import PAIR_A
from dashfakes import PAIR_B_FRAGMENT
from dashfakes import PAIR_B_INIT
from dashfakes import PROXY
from dashfakes import SPLIT_AUDIO
from dashfakes import SPLIT_MPD
from dashfakes import CdnHttp
from dashfakes import SplitHttp
from dashfakes import box
from dashfakes import fragment
from dashfakes import init
from dashfakes import initializations
from dashfakes import reps
from dashfakes import uuid

from resources.lib.stream import dash
from resources.lib.stream import manifest

MPD = (
    '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:cenc="urn:mpeg:cenc:2013"><Period id="1">'
    '<AdaptationSet contentType="video"><ContentProtection schemeIdUri="%(wv)s" value="Widevine"/>'
    '<SegmentTemplate media="v/$Time$" initialization="v/Init"><SegmentTimeline><S t="100" d="10" r="5"/>'
    "</SegmentTimeline></SegmentTemplate>"
    '<Representation id="v" bandwidth="2500000"/></AdaptationSet>'
    '<AdaptationSet contentType="audio" lang="hun"><ContentProtection schemeIdUri="%(wv)s" value="Widevine"/>'
    '<SegmentTemplate media="h/$Time$" initialization="h/Init"><SegmentTimeline><S t="1000" d="7"/><S d="8"/>'
    '<S d="7"/></SegmentTimeline></SegmentTemplate><Representation id="hun" bandwidth="96000"/></AdaptationSet>'
    '<AdaptationSet contentType="audio" lang="mul"><ContentProtection schemeIdUri="%(wv)s" value="Widevine"/>'
    '<SegmentTemplate media="m/$Time$" initialization="m/Init"><SegmentTimeline><S t="1000" d="7"/><S d="8"/>'
    '<S d="7"/></SegmentTimeline></SegmentTemplate><Representation id="mul" bandwidth="96000"/></AdaptationSet>'
    "</Period></MPD>" % {"wv": dash.WIDEVINE_URN}
)
LIVE = MPD.replace("<MPD ", '<MPD type="dynamic" ', 1)
FILES = {
    BASE + "v/Init": init("video-a", PAIR_A),
    BASE + "v/140": fragment("video-b", PAIR_B_FRAGMENT),  # newest but one of t=100..150
    BASE + "h/Init": init("audio-a", PAIR_A),
    BASE + "h/1007": fragment("audio-b", PAIR_B_FRAGMENT),  # newest but one of 1000, 1007, 1015
    BASE + "m/Init": init("audio-b", PAIR_B_INIT),
    BASE + "m/1007": fragment("audio-b", PAIR_B_FRAGMENT),
}
# The key change in SPLIT_MPD, in seconds into the stream (its segments are 1 s long).
SPLIT_AT = 23.0


def make_rewriter(http, **options):
    return manifest.ManifestRewriter(http, lambda: PROXY, lambda msg: None, **options)


def _fragments(http):
    return [u for u in http.fetched if not u.endswith("Init")]


def test_rotated_tracks_follow_their_fragments():
    http = CdnHttp(FILES)
    rewriter = make_rewriter(http)
    root, out = reps(rewriter.rewrite(MPD, MPD_URL).mpd)
    # All tracks now share pair B, so none is dropped, and the Hungarian audio
    # uses the fragments' key instead of its init segment's.
    assert out == {"v": uuid("video-b"), "hun": uuid("audio-b"), "mul": uuid("audio-b")}
    inits = initializations(root)
    assert inits[0].startswith(PROXY + "/init?u=") and inits[1].startswith(PROXY + "/init?u=")
    assert inits[2] == "m/Init"  # not rotated: straight from the CDN


def test_a_rotated_init_segment_served_through_the_proxy_names_the_fragments_key():
    http = CdnHttp(FILES)
    rewriter = make_rewriter(http)
    rewriter.rewrite(MPD, MPD_URL)
    data = dash.with_tenc_kid(http.files[BASE + "h/Init"], rewriter.init_kid(BASE + "h/Init"))
    assert KID["audio-b"] in data and KID["audio-a"] not in data.split(b"tenc")[1]


def test_a_manifest_refresh_fetches_no_segment_again():
    http = CdnHttp(FILES)
    rewriter = make_rewriter(http)
    rewriter.rewrite(MPD, MPD_URL)
    count = len(http.fetched)
    rewriter.rewrite(MPD, MPD_URL)
    assert len(http.fetched) == count


def test_a_catch_up_takes_the_keys_it_starts_with():
    # A catch-up's manifest is static and plays from its first fragment: that
    # one still has the init segments' pair A, only the end has rotated to B.
    files = dict(FILES)
    files[BASE + "v/100"] = fragment("video-a", PAIR_A)
    files[BASE + "h/1000"] = fragment("audio-a", PAIR_A)
    files[BASE + "m/1000"] = fragment("audio-b", PAIR_B_FRAGMENT)
    static = MPD.replace("<MPD ", '<MPD type="static" ', 1)
    root, out = reps(make_rewriter(CdnHttp(files)).rewrite(static, MPD_URL).mpd)
    assert out["v"] == uuid("video-a") and out["hun"] == uuid("audio-a")
    assert initializations(root)[0] == "v/Init"  # its own key: straight from the CDN, nothing rotated


def test_the_proxy_narrows_the_window_only_where_the_programme_says_so():
    live = MPD.replace("<MPD ", '<MPD type="dynamic" timeShiftBufferDepth="PT15M0S" ', 1)
    live = live.replace("<SegmentTemplate ", '<SegmentTemplate timescale="10" ')
    blocked = make_rewriter(CdnHttp(FILES), no_timeshift=lambda: True)
    assert 'timeShiftBufferDepth="PT%dS"' % dash.NO_TIMESHIFT_WINDOW in blocked.rewrite(live, MPD_URL).mpd
    free = make_rewriter(CdnHttp(FILES), no_timeshift=lambda: False)
    assert 'timeShiftBufferDepth="PT15M0S"' in free.rewrite(live, MPD_URL).mpd


def _kids(out):
    """Return {representation id: the default key id of its cenc ContentProtection}."""
    found = {}
    for rep in ET.fromstring(out.encode()).iter(MPD_TAG + "Representation"):
        cps = rep.findall(MPD_TAG + "ContentProtection")
        found[rep.get("id")] = next(c.get(CENC + "default_KID") for c in cps if c.get("value") == "cenc")
    return found


def test_a_catch_up_across_a_key_change_plays_its_first_part_first():
    http = SplitHttp()
    rewriter = make_rewriter(http)
    out = rewriter.rewrite(SPLIT_MPD, MPD_URL).mpd
    # One period, the whole timeline (its length, seeking), the first part's keys.
    assert out.count("<Period") == 1 and '<S t="100" d="10" r="39"/>' in out
    assert rewriter.change_times == (SPLIT_AT,) and rewriter.part == 0
    assert rewriter.part_of(SPLIT_AT - 1) == 0 and rewriter.part_of(SPLIT_AT) == 1
    assert _kids(out) == {"v": uuid("video-a"), "hun": uuid("audio-a")}
    # A binary search over the video, not every fragment: for 40 segments its first,
    # last and six more; the audio only around the change (and each track's first
    # fragment once more, read before the search).
    assert len(_fragments(http)) <= 12
    # The manifest asked again: nothing fetched again.
    count = len(http.fetched)
    assert rewriter.rewrite(SPLIT_MPD, MPD_URL).mpd == out and len(http.fetched) == count


def test_a_catch_ups_second_part_takes_the_new_keys_with_its_init_segments_named_so():
    out = make_rewriter(SplitHttp(), part=1).rewrite(SPLIT_MPD, MPD_URL).mpd
    assert _kids(out) == {"v": uuid("video-b"), "hun": uuid("audio-b")}
    init_url = re.search(r'initialization="([^"]+)"', out).group(1)
    assert init_url.startswith(PROXY + "/init?u=") and init_url.endswith("&amp;k=" + uuid("video-b"))


def test_a_catch_up_resumed_past_its_key_change_takes_that_parts_keys():
    resumed = make_rewriter(SplitHttp(), start_at=SPLIT_AT + 1)
    assert _kids(resumed.rewrite(SPLIT_MPD, MPD_URL).mpd)["v"] == uuid("video-b") and resumed.part == 1


def test_a_catch_up_without_a_key_change_stays_one_period():
    class Http(SplitHttp):
        def content(self, url):
            return super().content(url.replace("/4", "/1"))  # every fragment early: pair A

    rewriter = make_rewriter(Http())
    out = rewriter.rewrite(SPLIT_MPD.replace('r="39"', 'r="20"'), MPD_URL).mpd
    assert out.count("<Period") == 1 and rewriter.change_times == ()


def test_known_key_changes_need_no_search():
    first = make_rewriter(SplitHttp())
    expected = first.rewrite(SPLIT_MPD, MPD_URL).mpd
    assert first.change_times == (SPLIT_AT,)
    http = SplitHttp()
    again = make_rewriter(http, change_hint=first.found_changes)
    assert again.rewrite(SPLIT_MPD, MPD_URL).mpd == expected
    # Only the start fragments and each track's first fragment of the new key.
    assert len(_fragments(http)) == 4


def test_a_live_key_change_is_noticed_at_the_refresh_that_brings_it():
    """The newest fragments' keys are read at each refresh (once each); a new one is noted with its distance to the edge."""
    files = dict(FILES)
    http = CdnHttp(files)
    logged = []
    rewriter = make_rewriter(http, debug=logged.append, label="C1")
    rewriter.rewrite(LIVE, MPD_URL)
    assert rewriter.live_changes == ()  # the keys it started with
    count = len(http.fetched)
    rewriter.rewrite(LIVE, MPD_URL)
    assert len(http.fetched) == count  # the same newest fragments: not read again

    # Two segments later: the video's newest fragments name another key (the audio's do not).
    later = LIVE.replace('<S t="100" d="10" r="5"/>', '<S t="100" d="10" r="7"/>')
    files[BASE + "v/160"] = fragment("video-a", PAIR_A)
    rewriter.rewrite(later, MPD_URL)
    ((noticed, before_edge, track, old, new),) = rewriter.live_changes
    assert (before_edge, track, old, new) == (20.0, "video", uuid("video-b"), uuid("video-a"))
    assert any("live key change on C1 (video)" in m and uuid("video-a") in m for m in logged)
    # Noticed once: the next refresh with the same key adds nothing.
    files[BASE + "v/170"] = fragment("video-a", PAIR_A)
    rewriter.rewrite(later.replace('r="7"', 'r="8"'), MPD_URL)
    assert len(rewriter.live_changes) == 1


def test_a_catch_up_reads_no_live_keys():
    rewriter = make_rewriter(SplitHttp())
    rewriter.rewrite(SPLIT_MPD, MPD_URL)
    assert rewriter.live_changes == ()


def test_the_trick_mode_pictures_are_not_watched_for_live_key_changes():
    trick = (
        '<AdaptationSet contentType="video"><EssentialProperty schemeIdUri="%s" value="1"/>'
        '<ContentProtection schemeIdUri="%s" value="Widevine"/><SegmentTemplate media="t/$Time$" initialization="t/Init">'
        '<SegmentTimeline><S t="100" d="10" r="5"/></SegmentTimeline></SegmentTemplate>'
        '<Representation id="t" bandwidth="2500000"/></AdaptationSet>' % (dash.TRICK_MODE, dash.WIDEVINE_URN)
    )
    live = LIVE.replace('<Period id="1">', '<Period id="1">' + trick, 1)
    files = dict(FILES, **{BASE + "t/Init": init("video-a", PAIR_A), BASE + "t/140": fragment("video-a", PAIR_A)})
    http = CdnHttp(files)
    rewriter = make_rewriter(http)
    rewriter.rewrite(live, MPD_URL)
    # A refresh with a newer segment: the video's is read, the trick-mode pictures' (which ISA leaves out) not.
    files[BASE + "v/150"] = fragment("video-a", PAIR_A)
    http.fetched.clear()
    rewriter.rewrite(live.replace('r="5"', 'r="6"'), MPD_URL)
    assert http.fetched == [BASE + "v/150"]


def test_only_the_video_track_is_watched_for_live_key_changes():
    files = dict(FILES)
    http = CdnHttp(files)
    rewriter = make_rewriter(http)
    rewriter.rewrite(LIVE, MPD_URL)
    # The Hungarian sound's newest fragments now name another key, the video's not: not read, nothing noted.
    later = LIVE.replace('<S t="1000" d="7"/><S d="8"/>', '<S t="1000" d="7"/><S d="8"/><S d="7"/>', 1)
    files[BASE + "h/1015"] = fragment("audio-a", PAIR_A)
    rewriter.rewrite(later, MPD_URL)
    assert rewriter.live_changes == () and BASE + "h/1015" not in http.fetched


def test_a_key_change_to_no_key_plays_in_one_part_and_is_not_kept():
    class Http(SplitHttp):
        def content(self, url):
            track, time = url[len(BASE) :].split("/")
            if track == "h" and time != "Init" and int(time) >= SPLIT_AUDIO:
                return box(b"moof", b"")  # the sound's later fragments name no key
            return super().content(url)

    rewriter = make_rewriter(Http())
    rewriter.rewrite(SPLIT_MPD, MPD_URL)
    assert rewriter.change_times == () and rewriter.found_changes is None and rewriter.part == 0
