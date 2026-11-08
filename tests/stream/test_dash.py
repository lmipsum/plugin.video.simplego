"""The DASH helpers the proxy reads and rewrites manifests with: timelines and live edges."""

from resources.lib.stream import dash


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
