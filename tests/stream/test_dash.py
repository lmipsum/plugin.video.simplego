"""The DASH helpers the proxy reads and rewrites manifests with: timelines, live edges, keys in boxes and licences."""

import base64

import pytest
from dashfakes import KID
from dashfakes import PAIR_A
from dashfakes import PAIR_B_FRAGMENT
from dashfakes import PAIR_B_INIT
from dashfakes import box
from dashfakes import fragment_box
from dashfakes import init
from dashfakes import init_box
from dashfakes import pssh_box
from dashfakes import uuid

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


def test_tracks_are_told_apart_by_their_content_type_or_mime_type():
    assert dash.is_video('<AdaptationSet contentType="video">') and dash.is_video('<AdaptationSet mimeType="video/mp4">')
    assert dash.is_audio('<AdaptationSet mimeType="audio/mp4">') and not dash.is_audio('<AdaptationSet contentType="video">')
    assert dash.is_text('<AdaptationSet contentType="text">') and dash.is_text('<Representation codecs="stpp"/>')


def test_a_static_manifest_is_told_from_a_live_one():
    assert dash.is_static('<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">')
    assert not dash.is_static('<MPD type="dynamic"><Period type="static"/>')


def test_init_protection():
    pssh, kid = dash.init_protection(init_box(bytes.fromhex("00112233445566778899aabbccddeeff"), pssh_box(b"AA")))
    assert kid == "00112233-4455-6677-8899-aabbccddeeff"
    assert base64.b64decode(pssh)[4:8] == b"pssh"


def test_fragment_protection_reads_the_seig_key():
    pssh = pssh_box(b"BB")
    got_pssh, kid = dash.fragment_protection(fragment_box(bytes.fromhex("fedcba9876543210fedcba9876543210"), pssh))
    assert kid == "fedcba98-7654-3210-fedc-ba9876543210"
    assert base64.b64decode(got_pssh).endswith(b"BB")


def test_a_fragment_without_a_seig_box_names_no_key():
    assert dash.fragment_protection(box(b"moof", pssh_box(b"BB"))) == (None, None)


def _field(number, payload):
    """Return a protobuf field: a varint for an int, else length-delimited bytes."""
    if isinstance(payload, int):
        return bytes([number << 3, payload])
    return bytes([number << 3 | 2, len(payload)]) + payload


def test_licence_keys_reads_public_key_rules():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    content_key = _field(1, key) + _field(4, 2) + _field(5, 5) + _field(6, _field(1, 4))
    signing_key = _field(1, b"x") + _field(4, 1)
    licence = _field(1, 2) + _field(2, _field(3, signing_key) + _field(3, content_key))
    assert dash.licence_keys(licence) == ["0123456789abcdef0123456789abcdef HW_SECURE_ALL HDCP v2.2"]


def test_licence_keys_of_an_unreadable_licence_are_none():
    assert dash.licence_keys(b"\xff\xff") == []


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [(PAIR_B_INIT, PAIR_B_FRAGMENT, True), (PAIR_A, PAIR_B_INIT, False)],
)
def test_key_pair_ignores_box_bytes(first, second, same):
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    assert (dash.key_pair(b64(first)) == dash.key_pair(b64(second))) is same


def test_a_key_pair_not_in_a_box_is_itself():
    assert dash.key_pair("P1") == "P1"


def test_an_init_segment_is_named_another_key():
    assert KID["video-b"] in dash.with_tenc_kid(init("video-a", PAIR_A), uuid("video-b"))
