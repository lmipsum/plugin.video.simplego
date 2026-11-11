"""The manifest rewriter: the tracks kept by their key pairs and audio language, rotated tracks' init segments proxied."""

import pytest
from dashfakes import MPD_URL
from dashfakes import NS
from dashfakes import PROXY
from dashfakes import initializations
from dashfakes import reps

from resources.lib.stream import dash
from resources.lib.stream import manifest

MPD = (
    '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:cenc="urn:mpeg:cenc:2013" type="dynamic">'
    '<Period id="1">'
    '<AdaptationSet contentType="video"><ContentProtection schemeIdUri="%(wv)s" value="Widevine"/>'
    '<SegmentTemplate media="S!x/QualityLevels($Bandwidth$)/F($Time$)" initialization="S!x/QualityLevels($Bandwidth$)/F(Init)"/>'
    '<Representation id="sd" bandwidth="2500000" width="1280"/><Representation id="hd" bandwidth="3500000" width="1280"/>'
    "</AdaptationSet>"
    '<AdaptationSet contentType="audio"><ContentProtection schemeIdUri="%(wv)s" value="Widevine"/>'
    '<SegmentTemplate media="S!x/QualityLevels($Bandwidth$)/A($Time$)" initialization="S!x/QualityLevels($Bandwidth$)/A(Init)"/>'
    '<Representation id="a" bandwidth="96000"/>'
    "</AdaptationSet>"
    '<AdaptationSet contentType="subtitle"><Representation id="s" bandwidth="100"/></AdaptationSet>'
    "</Period></MPD>" % {"wv": dash.WIDEVINE_URN}
)
SD, HD, AUDIO = 2500000, 3500000, 96000


def make_rewriter(protection, audio_langs=(), debug=None):
    """A rewriter with these keys read already: no segment is fetched."""
    rewriter = manifest.ManifestRewriter(None, lambda: PROXY, lambda msg: None, debug=debug, audio_langs=audio_langs)
    # (pssh, kid) entries; a third item is the init's own kid where keys rotated.
    rewriter._protection.update({url: tuple(v) + (None,) * (3 - len(v)) for url, v in protection.items()})
    return rewriter


def init_url(kind, bandwidth):
    return "https://cdn.example/sdash/LIVE$1/index.mpd/S!x/QualityLevels(%s)/%s(Init)" % (bandwidth, kind)


def test_rewrite_single_key_pair_keeps_every_track():
    protection = {
        init_url("F", SD): ("P1", "k-sd"),
        init_url("F", HD): ("P1", "k-sd"),
        init_url("A", AUDIO): ("P1", "k-audio"),
    }
    root, out = reps(make_rewriter(protection).rewrite(MPD, MPD_URL).mpd)
    assert out == {"sd": "k-sd", "hd": "k-sd", "a": "k-audio", "s": None}
    assert root.find("d:BaseURL", NS).text == "https://cdn.example/sdash/LIVE$1/index.mpd/"


def test_rewrite_drops_video_tracks_keyed_apart_from_audio():
    # Audio and SD video share one pssh, HD video has its own.
    protection = {
        init_url("F", SD): ("P1", "k-sd"),
        init_url("F", HD): ("P2", "k-hd"),
        init_url("A", AUDIO): ("P1", "k-audio"),
    }
    _, out = reps(make_rewriter(protection).rewrite(MPD, MPD_URL).mpd)
    assert out == {"sd": "k-sd", "a": "k-audio", "s": None}


def test_rewrite_keeps_all_video_when_none_matches_audio():
    protection = {
        init_url("F", SD): ("P2", "k-sd"),
        init_url("F", HD): ("P3", "k-hd"),
        init_url("A", AUDIO): ("P1", "k-audio"),
    }
    _, out = reps(make_rewriter(protection).rewrite(MPD, MPD_URL).mpd)
    assert set(out) == {"sd", "hd", "a", "s"}


def test_rewrite_proxies_init_segments_of_rotated_tracks():
    protection = {
        init_url("F", SD): ("P2", "k-rotated", "k-init"),
        init_url("F", HD): ("P2", "k-rotated", "k-init"),
        init_url("A", AUDIO): ("P2", "k-audio"),
    }
    root, out = reps(make_rewriter(protection).rewrite(MPD, MPD_URL).mpd)
    assert out == {"sd": "k-rotated", "hd": "k-rotated", "a": "k-audio", "s": None}
    inits = initializations(root)
    assert inits[0].startswith(PROXY + "/init?u=https%3A%2F%2Fcdn.example%2F") and "$Bandwidth$" in inits[0]
    assert inits[1] == "S!x/QualityLevels($Bandwidth$)/A(Init)"


def two_pair_layout():
    """A manifest and its keys: main video and the Hungarian audio share one pssh, the other audio and trick play another."""

    def aset(kind, letter, lang, rep_id, bandwidth):
        return (
            '<AdaptationSet contentType="%s"%s><ContentProtection schemeIdUri="%s" value="Widevine"/>'
            '<SegmentTemplate media="S!x/QualityLevels($Bandwidth$)/%s($Time$)" '
            'initialization="S!x/QualityLevels($Bandwidth$)/%s(Init)"/>'
            '<Representation id="%s" bandwidth="%d"/></AdaptationSet>'
            % (kind, ' lang="%s"' % lang if lang else "", dash.WIDEVINE_URN, letter, letter, rep_id, bandwidth)
        )

    mpd = (
        '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:cenc="urn:mpeg:cenc:2013"><Period id="1">'
        + aset("video", "F", None, "v", SD)
        + aset("video", "T", None, "trick", SD)
        + aset("audio", "M", "mul", "a-mul", AUDIO)
        + aset("audio", "A", "hun", "a-hun", AUDIO)
        + "</Period></MPD>"
    )
    protection = {
        init_url("F", SD): ("P1", "k-video"),
        init_url("T", SD): ("P2", "k-trick"),
        init_url("M", AUDIO): ("P2", "k-mul"),
        init_url("A", AUDIO): ("P1", "k-hun"),
    }
    return mpd, protection


def test_rewrite_keeps_only_the_hungarian_audios_key_pair():
    mpd, protection = two_pair_layout()
    root, out = reps(make_rewriter(protection).rewrite(mpd, MPD_URL).mpd)
    assert out == {"v": "k-video", "a-hun": "k-hun"}
    assert len(root.findall("d:Period/d:AdaptationSet", NS)) == 2


@pytest.mark.parametrize(
    ("preferred", "kept"),
    [
        ("mul", {"trick": "k-trick", "a-mul": "k-mul"}),
        ("eng", {"v": "k-video", "a-hun": "k-hun"}),  # a language the channel does not have: Hungarian
    ],
)
def test_rewrite_follows_the_preferred_audio_language(preferred, kept):
    mpd, protection = two_pair_layout()
    _, out = reps(make_rewriter(protection, [preferred]).rewrite(mpd, MPD_URL).mpd)
    assert out == kept


def test_the_video_tracks_offered_are_logged_once_with_their_key_pairs():
    mpd, protection = two_pair_layout()
    logged = []
    rewriter = make_rewriter(protection, debug=logged.append)
    rewriter.rewrite(mpd, MPD_URL)
    rewriter.rewrite(mpd, MPD_URL)  # a live manifest's refresh: not again
    assert logged == ["video tracks offered: ? 2.5 Mbit/s pair 1; ? 2.5 Mbit/s pair 2 (dropped)", "subtitle tracks offered: none"]


def test_each_subtitle_track_offered_is_logged_with_its_language_format_and_role():
    _, protection = two_pair_layout()
    text = '<AdaptationSet contentType="text" lang="hun"><Role value="subtitle"/><Representation codecs="stpp"/></AdaptationSet>'
    logged = []
    rewriter = make_rewriter(protection, debug=logged.append)
    rewriter._log_tracks([text, text.replace("hun", "eng")], lambda aset, tag: (None,), None)
    assert logged[-1] == "subtitle tracks offered: hun stpp subtitle; eng stpp subtitle"
