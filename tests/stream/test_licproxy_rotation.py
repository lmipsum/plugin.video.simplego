"""Key rotation as on RTL HD: init segments name one key pair, the fragments another."""

import base64
import re
import xml.etree.ElementTree as ET

from test_licproxy import MPD_URL
from test_licproxy import box
from test_licproxy import reps

from resources.lib.net import localserver
from resources.lib.stream import dash
from resources.lib.stream import licproxy
from resources.lib.stream import manifest

KID = {name: bytes([n]) * 16 for n, name in enumerate(["video-a", "audio-a", "video-b", "audio-b"], 1)}


def pssh(*names, extra=b""):
    data = b"".join(b"\x12\x10" + KID[n] for n in names) + extra
    return box(b"pssh", bytes(4) + dash.WIDEVINE_SYSTEM_ID + len(data).to_bytes(4, "big") + data)


def init(kid, pair):
    tenc = box(b"tenc", bytes(4) + bytes([0, 0, 1, 8]) + KID[kid])
    return box(b"moov", pair + box(b"trak", tenc))


def fragment(kid, pair):
    seig = b"seig" + (20).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([0, 0, 1, 8]) + KID[kid]
    return box(b"moof", box(b"traf", box(b"sgpd", (1 << 24).to_bytes(4, "big") + seig)) + pair)


PAIR_A = pssh("video-a", "audio-a")
# The same pair B, once as the init segments carry it, once as the fragments do.
PAIR_B_INIT = pssh("video-b", "audio-b")
PAIR_B_FRAGMENT = pssh("video-b", "audio-b", extra=b"\x1a\x03tag")

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
BASE = "https://cdn.example/sdash/LIVE$1/index.mpd/"
FILES = {
    BASE + "v/Init": init("video-a", PAIR_A),
    BASE + "v/140": fragment("video-b", PAIR_B_FRAGMENT),  # newest but one of t=100..150
    BASE + "h/Init": init("audio-a", PAIR_A),
    BASE + "h/1007": fragment("audio-b", PAIR_B_FRAGMENT),  # newest but one of 1000, 1007, 1015
    BASE + "m/Init": init("audio-b", PAIR_B_INIT),
    BASE + "m/1007": fragment("audio-b", PAIR_B_FRAGMENT),
}


class FakeHttp:
    def __init__(self, files=None):
        self.files = files or FILES
        self.fetched = []

    def get(self, url, headers=None, timeout=None):
        self.fetched.append(url)
        files = self.files

        class Response:
            content = files[url]
            status_code = 200

            def raise_for_status(self):
                pass

        return Response()

    def close(self):
        pass


def make_rewriter(http, **options):
    return manifest.ManifestRewriter(http, lambda: "http://127.0.0.1:1", lambda msg: None, **options)


def uuid(name):
    return dash.uuid(KID[name])


def test_rotated_tracks_follow_their_fragments():
    http = FakeHttp()
    proxy = make_rewriter(http)
    root, out = reps(proxy.rewrite(MPD, MPD_URL).mpd)
    # All tracks now share pair B, so none is dropped, and the Hungarian audio
    # uses the fragments' key instead of its init segment's.
    assert out == {"v": uuid("video-b"), "hun": uuid("audio-b"), "mul": uuid("audio-b")}
    inits = [t.get("initialization") for t in root.iter("{urn:mpeg:dash:schema:mpd:2011}SegmentTemplate")]
    assert inits[0].startswith("http://127.0.0.1:1/init?u=") and inits[1].startswith("http://127.0.0.1:1/init?u=")
    assert inits[2] == "m/Init"  # not rotated: straight from the CDN

    # The init segment served through the proxy names the fragments' key.
    data = dash.with_tenc_kid(http.files[BASE + "h/Init"], proxy.init_kid(BASE + "h/Init"))
    assert KID["audio-b"] in data and KID["audio-a"] not in data.split(b"tenc")[1]

    # A manifest refresh fetches nothing again.
    count = len(http.fetched)
    proxy.rewrite(MPD, MPD_URL)
    assert len(http.fetched) == count


def test_key_pair_ignores_box_bytes():
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    assert dash.key_pair(b64(PAIR_B_INIT)) == dash.key_pair(b64(PAIR_B_FRAGMENT))
    assert dash.key_pair(b64(PAIR_A)) != dash.key_pair(b64(PAIR_B_INIT))
    assert dash.key_pair("P1") == "P1"


def test_live_edges_are_aligned():
    # The audio already has the next segment, the video not yet.
    mpd = (
        '<MPD><Period><AdaptationSet contentType="video"><SegmentTemplate timescale="10">'
        '<SegmentTimeline><S t="1000" d="40" r="2"/></SegmentTimeline></SegmentTemplate></AdaptationSet>'
        '<AdaptationSet contentType="audio"><SegmentTemplate timescale="48000"><SegmentTimeline>'
        '<S t="4800500" d="192512"/><S d="191488"/><S d="192512"/><S d="191488"/></SegmentTimeline>'
        "</SegmentTemplate></AdaptationSet></Period></MPD>"
    )
    out = dash.align_live_edges(mpd)
    assert '<S t="1000" d="40" r="2"/>' in out  # video untouched: it sets the common edge
    assert '<SegmentTimeline><S t="4800500" d="192512"/><S d="191488"/><S d="192512"/></SegmentTimeline>' in out
    assert dash.align_live_edges(out) == out


def test_a_timeline_reads_its_starts_durations_and_repeats():
    template = (
        '<SegmentTemplate timescale="10" media="m/$Time$"><SegmentTimeline>'
        '<S t="100" d="40" r="1"/><S d="38"/><S d="40" r="-1"/><S t="300" d="40"/></SegmentTimeline></SegmentTemplate>'
    )
    assert dash.parse_timeline(template) == (10, [(100, 40), (140, 40), (180, 38), (218, 40), (300, 40)])
    assert dash.parse_timeline('<SegmentTemplate><S t="0" d="40"/></SegmentTemplate>', default_scale=1) == (1, [(0, 40)])
    assert dash.parse_timeline('<SegmentTemplate timescale="10"><S t="0"/></SegmentTemplate>') == (None, [])  # no duration
    assert dash.parse_timeline('<SegmentTemplate media="m/$Time$"/>') == (None, [])  # no timeline


def test_a_catch_up_takes_the_keys_it_starts_with():
    # A catch-up's manifest is static and plays from its first fragment: that
    # one still has the init segments' pair A, only the end has rotated to B.
    files = dict(FILES)
    files[BASE + "v/100"] = fragment("video-a", PAIR_A)
    files[BASE + "h/1000"] = fragment("audio-a", PAIR_A)
    files[BASE + "m/1000"] = fragment("audio-b", PAIR_B_FRAGMENT)
    proxy = make_rewriter(FakeHttp(files))
    static = MPD.replace("<MPD ", '<MPD type="static" ', 1)
    root, out = reps(proxy.rewrite(static, MPD_URL).mpd)
    assert out["v"] == uuid("video-a") and out["hun"] == uuid("audio-a")
    inits = [t.get("initialization") for t in root.iter("{urn:mpeg:dash:schema:mpd:2011}SegmentTemplate")]
    assert inits[0] == "v/Init"  # its own key: straight from the CDN, nothing rotated


def test_no_timeshift_keeps_only_the_live_edge():
    mpd = (
        '<MPD type="dynamic" timeShiftBufferDepth="PT15M0S"><Period><AdaptationSet contentType="video">'
        '<SegmentTemplate timescale="10"><SegmentTimeline><S t="1000" d="40" r="224"/></SegmentTimeline>'
        "</SegmentTemplate></AdaptationSet></Period></MPD>"
    )
    out = dash.align_live_edges(mpd, 20)
    # 225 segments of 4 s, up to 1000 s: the ones starting in the last 20 s stay.
    assert '<SegmentTimeline><S t="9800" d="40" r="4"/></SegmentTimeline>' in out
    assert 'timeShiftBufferDepth="PT20S"' in out
    assert dash.align_live_edges(mpd) == mpd  # one track, no window: as it was


def test_the_proxy_narrows_the_window_only_where_the_programme_says_so():
    live = MPD.replace("<MPD ", '<MPD type="dynamic" timeShiftBufferDepth="PT15M0S" ', 1)
    live = live.replace("<SegmentTemplate ", '<SegmentTemplate timescale="10" ')
    blocked = make_rewriter(FakeHttp(), no_timeshift=lambda: True)
    assert 'timeShiftBufferDepth="PT%dS"' % dash.NO_TIMESHIFT_WINDOW in blocked.rewrite(live, MPD_URL).mpd
    free = make_rewriter(FakeHttp(), no_timeshift=lambda: False)
    assert 'timeShiftBufferDepth="PT15M0S"' in free.rewrite(live, MPD_URL).mpd


SPLIT_MPD = (
    '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:cenc="urn:mpeg:cenc:2013" type="static"'
    ' mediaPresentationDuration="PT40S"><Period id="1" start="PT0S">'
    '<AdaptationSet contentType="video"><ContentProtection schemeIdUri="%(wv)s" value="Widevine"/>'
    '<SegmentTemplate timescale="10" media="v/$Time$" initialization="v/Init"><SegmentTimeline><S t="100" d="10" r="39"/>'
    "</SegmentTimeline></SegmentTemplate>"
    '<Representation id="v" bandwidth="2500000"/></AdaptationSet>'
    '<AdaptationSet contentType="audio" lang="hun"><ContentProtection schemeIdUri="%(wv)s" value="Widevine"/>'
    '<SegmentTemplate timescale="10" media="h/$Time$" initialization="h/Init"><SegmentTimeline><S t="98" d="10" r="39"/>'
    '</SegmentTimeline></SegmentTemplate><Representation id="hun" bandwidth="96000"/></AdaptationSet>'
    "</Period></MPD>" % {"wv": dash.WIDEVINE_URN}
)


class SplitHttp(FakeHttp):
    """Fragments before t=330 (video) / 328 (audio) have pair A, the rest pair B."""

    def get(self, url, headers=None, timeout=None):
        self.fetched.append(url)
        name = url[len(BASE) :]
        track, time = name.split("/")
        if time == "Init":
            content = init("video-a" if track == "v" else "audio-a", PAIR_A)
        else:
            late = int(time) >= (330 if track == "v" else 328)
            kid = ("video-" if track == "v" else "audio-") + ("b" if late else "a")
            content = fragment(kid, PAIR_B_FRAGMENT if late else PAIR_A)

        class Response:
            status_code = 200

            def raise_for_status(self):
                pass

        response = Response()
        response.content = content
        return response


def _kids(out):
    root = ET.fromstring(out.encode())
    found = {}
    for rep in root.iter("{urn:mpeg:dash:schema:mpd:2011}Representation"):
        cps = rep.findall("{urn:mpeg:dash:schema:mpd:2011}ContentProtection")
        found[rep.get("id")] = next(c.get("{urn:mpeg:cenc:2013}default_KID") for c in cps if c.get("value") == "cenc")
    return found


def test_a_catch_up_across_a_key_change_plays_in_parts():
    http = SplitHttp()
    proxy = make_rewriter(http)
    out = proxy.rewrite(SPLIT_MPD, MPD_URL).mpd
    # One period, the whole timeline (its length, seeking), the first part's keys.
    assert out.count("<Period") == 1 and '<S t="100" d="10" r="39"/>' in out
    assert proxy.change_times == (23.0,) and proxy.part == 0
    assert proxy.part_of(10) == 0 and proxy.part_of(23) == 1
    assert _kids(out) == {"v": uuid("video-a"), "hun": uuid("audio-a")}
    # A binary search over the video, not every fragment: for 40 segments its first,
    # last and six more; the audio only around the change (and each track's first
    # fragment once more, read before the search).
    assert len([u for u in http.fetched if not u.endswith("Init")]) <= 12
    # The manifest asked again: nothing fetched again.
    count = len(http.fetched)
    assert proxy.rewrite(SPLIT_MPD, MPD_URL).mpd == out and len(http.fetched) == count

    # The second part: the same manifest with the new keys, its init segments named so.
    later = make_rewriter(SplitHttp(), part=1)
    out = later.rewrite(SPLIT_MPD, MPD_URL).mpd
    assert _kids(out) == {"v": uuid("video-b"), "hun": uuid("audio-b")}
    init_url = re.search(r'initialization="([^"]+)"', out).group(1)
    assert init_url.startswith("http://127.0.0.1:1/init?u=") and init_url.endswith("&amp;k=" + uuid("video-b"))
    assert KID["video-b"] in dash.with_tenc_kid(init("video-a", PAIR_A), uuid("video-b"))
    # Started where it was left off, past the change: that part's keys.
    resumed = make_rewriter(SplitHttp(), start_at=30)
    assert _kids(resumed.rewrite(SPLIT_MPD, MPD_URL).mpd)["v"] == uuid("video-b") and resumed.part == 1


def test_a_catch_up_without_a_key_change_stays_one_period():
    class Http(SplitHttp):
        def get(self, url, headers=None, timeout=None):
            return super().get(url.replace("/4", "/1"), headers, timeout)  # every fragment early: pair A

    proxy = make_rewriter(Http())
    out = proxy.rewrite(SPLIT_MPD.replace('r="39"', 'r="20"'), MPD_URL).mpd
    assert out.count("<Period") == 1 and proxy.change_times == ()


def test_known_key_changes_need_no_search():
    first = make_rewriter(SplitHttp())
    expected = first.rewrite(SPLIT_MPD, MPD_URL).mpd
    assert first.change_times == (23.0,)  # 23 segments of 1 s into the stream
    http = SplitHttp()
    again = make_rewriter(http, change_hint=first.found_changes)
    assert again.rewrite(SPLIT_MPD, MPD_URL).mpd == expected
    # Only the start fragments and each track's first fragment of the new key.
    assert len([u for u in http.fetched if not u.endswith("Init")]) == 4


def test_a_static_manifest_is_made_once():
    class Http(SplitHttp):
        def get(self, url, headers=None, timeout=None):
            if url != MPD_URL:
                return super().get(url, headers, timeout)
            self.fetched.append(url)

            class Response:
                text = SPLIT_MPD

                def raise_for_status(self):
                    pass

            response = Response()
            response.url = url
            return response

    http = Http()
    proxy = licproxy.LicenceProxy(http, "https://licence", {}, lambda msg: None, manifest_url=MPD_URL).start()
    ask = localserver.Request("GET", "/manifest", {}, b"")
    try:
        first = proxy.respond(ask)
        assert first.status == 200 and b"<Period" in first.content
        count = len(http.fetched)
        # Asked again (the player opening it after the prefetch): served as made, nothing fetched.
        assert proxy.respond(ask) == first and len(http.fetched) == count
    finally:
        proxy.stop()


def test_a_live_key_change_is_noticed_at_the_refresh_that_brings_it():
    """The newest fragments' keys are read at each refresh (once each); a new one is noted with its distance to the edge."""
    files = dict(FILES)
    live = MPD.replace("<MPD ", '<MPD type="dynamic" ', 1)
    http = FakeHttp(files)
    logged = []
    proxy = make_rewriter(http, debug=logged.append, label="RTL")
    proxy.rewrite(live, MPD_URL)
    assert proxy.live_changes == ()  # the keys it started with
    count = len(http.fetched)
    proxy.rewrite(live, MPD_URL)
    assert len(http.fetched) == count  # the same newest fragments: not read again

    # Two segments later: the video's newest fragments name another key (the audio's do not).
    later = live.replace('<S t="100" d="10" r="5"/>', '<S t="100" d="10" r="7"/>')
    files[BASE + "v/160"] = fragment("video-a", PAIR_A)
    proxy.rewrite(later, MPD_URL)
    ((noticed, before_edge, track, old, new),) = proxy.live_changes
    assert (before_edge, track, old, new) == (20.0, "video", uuid("video-b"), uuid("video-a"))
    assert any("live key change on RTL (video)" in m and uuid("video-a") in m for m in logged)
    # Noticed once: the next refresh with the same key adds nothing.
    files[BASE + "v/170"] = fragment("video-a", PAIR_A)
    proxy.rewrite(later.replace('r="7"', 'r="8"'), MPD_URL)
    assert len(proxy.live_changes) == 1


def test_a_catch_up_reads_no_live_keys():
    proxy = make_rewriter(SplitHttp())
    proxy.rewrite(SPLIT_MPD, MPD_URL)
    assert proxy.live_changes == ()


def test_only_the_video_track_is_watched_for_live_key_changes():
    files = dict(FILES)
    live = MPD.replace("<MPD ", '<MPD type="dynamic" ', 1)
    http = FakeHttp(files)
    proxy = make_rewriter(http)
    proxy.rewrite(live, MPD_URL)
    # The Hungarian sound's newest fragments now name another key, the video's not: not read, nothing noted.
    later = live.replace('<S t="1000" d="7"/><S d="8"/>', '<S t="1000" d="7"/><S d="8"/><S d="7"/>', 1)
    files[BASE + "h/1015"] = fragment("audio-a", PAIR_A)
    proxy.rewrite(later, MPD_URL)
    assert proxy.live_changes == () and BASE + "h/1015" not in http.fetched
