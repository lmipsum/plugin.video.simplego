"""MP4 boxes, DASH manifests and a CDN serving them, as the stream tests build them.

Key pairs are named by the key ids they hold (see KID); a rotated track's init segment
names one pair and its fragments another.
"""

import xml.etree.ElementTree as ET

from resources.lib.stream import dash

NS = {"d": "urn:mpeg:dash:schema:mpd:2011", "cenc": "urn:mpeg:cenc:2013"}
MPD_TAG = "{urn:mpeg:dash:schema:mpd:2011}"
CENC = "{urn:mpeg:cenc:2013}"
# A tenc or seig box's flags before its key id: protected, 8-byte IVs.
PROTECTED = bytes([0, 0, 1, 8])

MPD_URL = "https://cdn.example/sdash/LIVE$1/index.mpd/Manifest?start=LIVE"
BASE = "https://cdn.example/sdash/LIVE$1/index.mpd/"
PROXY = "http://127.0.0.1:1"

KID = {name: bytes([n]) * 16 for n, name in enumerate(["video-a", "audio-a", "video-b", "audio-b"], 1)}


def box(kind, payload):
    """Return an MP4 box of this kind around payload."""
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


def pssh_box(data):
    """Return a Widevine pssh box holding data."""
    return box(b"pssh", bytes(4) + dash.WIDEVINE_SYSTEM_ID + len(data).to_bytes(4, "big") + data)


def pssh(*names, extra=b""):
    """Return a pssh box naming these keys (see KID), with extra bytes after them."""
    return pssh_box(b"".join(b"\x12\x10" + KID[n] for n in names) + extra)


def init_box(kid, pair):
    """Return an init segment whose track is keyed with kid (16 bytes) and that carries the pssh box pair."""
    return box(b"moov", pair + box(b"trak", box(b"tenc", bytes(4) + PROTECTED + kid)))


def fragment_box(kid, pair):
    """Return a fragment whose samples are keyed with kid (16 bytes) and that carries the pssh box pair."""
    seig = b"seig" + (20).to_bytes(4, "big") + (1).to_bytes(4, "big") + PROTECTED + kid
    return box(b"moof", box(b"traf", box(b"sgpd", (1 << 24).to_bytes(4, "big") + seig)) + pair)


def init(name, pair):
    """Return an init segment keyed with the named key (see KID)."""
    return init_box(KID[name], pair)


def fragment(name, pair):
    """Return a fragment keyed with the named key (see KID)."""
    return fragment_box(KID[name], pair)


def uuid(name):
    """Return the named key's id as a manifest writes it."""
    return dash.uuid(KID[name])


PAIR_A = pssh("video-a", "audio-a")
# The same pair B, once as the init segments carry it, once as the fragments do.
PAIR_B_INIT = pssh("video-b", "audio-b")
PAIR_B_FRAGMENT = pssh("video-b", "audio-b", extra=b"\x1a\x03tag")


def reps(mpd):
    """Return the manifest's root and {representation id: its default key id, or None}."""
    root = ET.fromstring(mpd.encode())
    out = {}
    for rep in root.iter(MPD_TAG + "Representation"):
        kids = [cp.get(CENC + "default_KID") for cp in rep.findall("d:ContentProtection", NS) if cp.get(CENC + "default_KID")]
        out[rep.get("id")] = kids[0] if kids else None
    return root, out


def initializations(root):
    """Return each SegmentTemplate's initialization address, in order."""
    return [t.get("initialization") for t in root.iter(MPD_TAG + "SegmentTemplate")]


class Response:
    """An HTTP response with this content (or text) and URL."""

    status_code = 200

    def __init__(self, content=b"", text="", url=""):
        self.content, self.text, self.url = content, text, url

    def raise_for_status(self):
        pass


class CdnHttp:
    """A CDN serving these files by URL; what was fetched kept."""

    def __init__(self, files):
        self.files = files
        self.fetched = []

    def get(self, url, headers=None, timeout=None):
        self.fetched.append(url)
        return Response(self.content(url))

    def content(self, url):
        return self.files[url]

    def close(self):
        pass


# A catch-up of 40 one-second segments; its keys change from pair A to pair B at SPLIT_VIDEO / SPLIT_AUDIO.
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
SPLIT_VIDEO, SPLIT_AUDIO = 330, 328


class SplitHttp(CdnHttp):
    """A CDN serving SPLIT_MPD's segments: fragments before its key change have pair A, the rest pair B."""

    def __init__(self):
        super().__init__({})

    def content(self, url):
        track, time = url[len(BASE) :].split("/")
        video = track == "v"
        if time == "Init":
            return init("video-a" if video else "audio-a", PAIR_A)
        late = int(time) >= (SPLIT_VIDEO if video else SPLIT_AUDIO)
        kid = ("video-" if video else "audio-") + ("b" if late else "a")
        return fragment(kid, PAIR_B_FRAGMENT if late else PAIR_A)
