import base64
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

from resources.lib.net import localserver
from resources.lib.net import transport
from resources.lib.stream import dash
from resources.lib.stream import licproxy
from resources.lib.stream import manifest

NS = {"d": "urn:mpeg:dash:schema:mpd:2011", "cenc": "urn:mpeg:cenc:2013"}
CENC = "{urn:mpeg:cenc:2013}"


def box(kind, payload):
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


def init_segment(kid_hex, pssh_tag):
    pssh = box(b"pssh", bytes(4) + dash.WIDEVINE_SYSTEM_ID + (2).to_bytes(4, "big") + pssh_tag)
    tenc = box(b"tenc", bytes(4) + b"\x00\x00\x01\x08" + bytes.fromhex(kid_hex))
    return box(b"moov", pssh + box(b"trak", tenc))


def test_init_protection():
    seg = init_segment("00112233445566778899aabbccddeeff", b"AA")
    pssh, kid = dash.init_protection(seg)
    assert kid == "00112233-4455-6677-8899-aabbccddeeff"
    assert base64.b64decode(pssh)[4:8] == b"pssh"


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
MPD_URL = "https://cdn.example/sdash/LIVE$1/index.mpd/Manifest?start=LIVE"


def make_rewriter(protection, audio_langs=(), debug=None):
    """A rewriter with these keys read already: no segment is fetched."""
    rewriter = manifest.ManifestRewriter(
        None, lambda: "http://127.0.0.1:1", lambda msg: None, debug=debug, audio_langs=audio_langs
    )
    # (pssh, kid) entries; a third item is the init's own kid where keys rotated.
    rewriter._protection.update({url: tuple(v) + (None,) * (3 - len(v)) for url, v in protection.items()})
    return rewriter


def reps(mpd):
    root = ET.fromstring(mpd.encode())
    out = {}
    for rep in root.iter("{urn:mpeg:dash:schema:mpd:2011}Representation"):
        kids = [cp.get(CENC + "default_KID") for cp in rep.findall("d:ContentProtection", NS) if cp.get(CENC + "default_KID")]
        out[rep.get("id")] = kids[0] if kids else None
    return root, out


def init_url(kind, bandwidth):
    return "https://cdn.example/sdash/LIVE$1/index.mpd/S!x/QualityLevels(%s)/%s(Init)" % (bandwidth, kind)


def test_rewrite_single_key_pair_keeps_every_track():
    protection = {
        init_url("F", 2500000): ("P1", "k-sd"),
        init_url("F", 3500000): ("P1", "k-sd"),
        init_url("A", 96000): ("P1", "k-audio"),
    }
    root, out = reps(make_rewriter(protection).rewrite(MPD, MPD_URL).mpd)
    assert out == {"sd": "k-sd", "hd": "k-sd", "a": "k-audio", "s": None}
    assert root.find("d:BaseURL", NS).text == "https://cdn.example/sdash/LIVE$1/index.mpd/"


def test_rewrite_drops_video_tracks_keyed_apart_from_audio():
    # Film+ HD layout: audio and SD video share one pssh, HD video has its own.
    protection = {
        init_url("F", 2500000): ("P1", "k-sd"),
        init_url("F", 3500000): ("P2", "k-hd"),
        init_url("A", 96000): ("P1", "k-audio"),
    }
    _, out = reps(make_rewriter(protection).rewrite(MPD, MPD_URL).mpd)
    assert out == {"sd": "k-sd", "a": "k-audio", "s": None}


def test_rewrite_keeps_all_video_when_none_matches_audio():
    protection = {
        init_url("F", 2500000): ("P2", "k-sd"),
        init_url("F", 3500000): ("P3", "k-hd"),
        init_url("A", 96000): ("P1", "k-audio"),
    }
    _, out = reps(make_rewriter(protection).rewrite(MPD, MPD_URL).mpd)
    assert set(out) == {"sd", "hd", "a", "s"}


def rtl_layout():
    # RTL HD layout: main video + Hungarian audio share one pssh; the original
    # language audio and the trick-play video have another. Unlicensed audio
    # used to reach the decoder still encrypted and crashed Kodi.
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
        + aset("video", "F", None, "v", 2500000)
        + aset("video", "T", None, "trick", 2500000)
        + aset("audio", "M", "mul", "a-mul", 96000)
        + aset("audio", "A", "hun", "a-hun", 96000)
        + "</Period></MPD>"
    )
    protection = {
        init_url("F", 2500000): ("P1", "k-video"),
        init_url("T", 2500000): ("P2", "k-trick"),
        init_url("M", 96000): ("P2", "k-mul"),
        init_url("A", 96000): ("P1", "k-hun"),
    }
    return mpd, protection


def test_rewrite_keeps_only_the_hungarian_audios_key_pair():
    mpd, protection = rtl_layout()
    root, out = reps(make_rewriter(protection).rewrite(mpd, MPD_URL).mpd)
    assert out == {"v": "k-video", "a-hun": "k-hun"}
    assert len(root.findall("d:Period/d:AdaptationSet", NS)) == 2


def test_rewrite_follows_the_preferred_audio_language():
    mpd, protection = rtl_layout()
    _, out = reps(make_rewriter(protection, ["mul"]).rewrite(mpd, MPD_URL).mpd)
    assert out == {"trick": "k-trick", "a-mul": "k-mul"}
    # A language the channel does not have falls back to Hungarian.
    _, out = reps(make_rewriter(protection, ["eng"]).rewrite(mpd, MPD_URL).mpd)
    assert out == {"v": "k-video", "a-hun": "k-hun"}


def test_licence_keys_reads_public_key_rules():
    def field(number, payload):
        if isinstance(payload, int):
            return bytes([number << 3, payload])
        return bytes([number << 3 | 2, len(payload)]) + payload

    content_key = field(1, bytes.fromhex("0123456789abcdef0123456789abcdef")) + field(4, 2) + field(5, 5) + field(6, field(1, 4))
    signing_key = field(1, b"x") + field(4, 1)
    licence = field(1, 2) + field(2, field(3, signing_key) + field(3, content_key))
    assert dash.licence_keys(licence) == ["0123456789abcdef0123456789abcdef HW_SECURE_ALL HDCP v2.2"]
    assert dash.licence_keys(b"\xff\xff") == []


def test_fragment_protection_reads_the_seig_key():
    pssh = box(b"pssh", bytes(4) + dash.WIDEVINE_SYSTEM_ID + (2).to_bytes(4, "big") + b"BB")
    kid = bytes.fromhex("fedcba9876543210fedcba9876543210")
    seig = b"seig" + (20).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\x00\x00\x01\x08" + kid
    fragment = box(b"moof", box(b"traf", box(b"sgpd", (1 << 24).to_bytes(4, "big") + seig)) + pssh)
    got_pssh, kid = dash.fragment_protection(fragment)
    assert kid == "fedcba98-7654-3210-fedc-ba9876543210"
    assert base64.b64decode(got_pssh).endswith(b"BB")
    assert dash.fragment_protection(box(b"moof", pssh)) == (None, None)


def test_rewrite_proxies_init_segments_of_rotated_tracks():
    protection = {
        init_url("F", 2500000): ("P2", "k-rotated", "k-init"),
        init_url("F", 3500000): ("P2", "k-rotated", "k-init"),
        init_url("A", 96000): ("P2", "k-audio"),
    }
    mpd = make_rewriter(protection).rewrite(MPD, MPD_URL).mpd
    root, out = reps(mpd)
    assert out == {"sd": "k-rotated", "hd": "k-rotated", "a": "k-audio", "s": None}
    inits = [t.get("initialization") for t in root.iter("{urn:mpeg:dash:schema:mpd:2011}SegmentTemplate")]
    assert inits[0].startswith("http://127.0.0.1:1/init?u=https%3A%2F%2Fcdn.example%2F") and "$Bandwidth$" in inits[0]
    assert inits[1] == "S!x/QualityLevels($Bandwidth$)/A(Init)"


def test_a_refused_licence_is_reported_once_and_ends_playback():
    reported = []
    done = threading.Event()

    class Http:
        posts = 0

        def post(self, url, data=None, headers=None, timeout=None):
            Http.posts += 1

            class Response:
                status_code = 403
                content = b"<error><code>3099</code><message>browser framework is not trusted</message></error>"
                text = content.decode()
                headers = {"Content-Type": "text/xml"}

            return Response()

        def close(self):
            pass

    on_refused = lambda code: (reported.append(code), done.set())  # noqa: E731
    proxy = licproxy.LicenceProxy(Http(), "https://licence", {}, lambda msg: None, on_refused, "https://cdn/index.mpd").start()
    try:
        for _ in range(3):  # ISA asks again for each track
            assert proxy.respond(localserver.Request("POST", "/license", {}, b"challenge")).status == 403
        assert done.wait(2) and reported == ["3099"] and Http.posts == 1
        # The manifest refresh stops too.
        assert proxy.respond(localserver.Request("GET", "/manifest", {}, b"")).status == 410
    finally:
        proxy.stop()


def test_a_sleeping_proxy_reopens_and_relays_to_the_new_stream():
    new = licproxy.LicenceProxy(transport.Session(), "http://unused", {}, lambda msg: None, manifest_url=None).start()
    old = licproxy.LicenceProxy(transport.Session(), "http://unused", {}, lambda msg: None).start()
    reopened = []
    local = transport.Session()
    old.sleep(lambda: reopened.append(1) or new.manifest.rsplit("/", 1)[0])
    try:
        # The new stream's proxy answers (here: no manifest, 404) through the old address.
        assert local.get(old.manifest, timeout=5).status_code == 404
        assert local.get(old.manifest, timeout=5).status_code == 404
        assert reopened == [1]  # reopened once, then relayed
        new.stop()
        assert local.get(old.manifest, timeout=5).status_code in (404, 503)  # gone: reopened again
        assert len(reopened) == 2
    finally:
        old.stop()


def test_the_proxy_over_the_add_on_s_own_http_end_to_end():
    class Provider(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            ok = body == b"challenge" and self.headers.get("X-Token") == "t1"
            self._send(200 if ok else 403, b"licence" if ok else b"<error><code>3099</code><message>no</message></error>")

        def do_GET(self):
            self._send(200, b"\x00\x00\x00\x08ftyp" + b"init" * 4)  # an init segment without a tenc box

        def _send(self, status, body):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    proxy = licproxy.LicenceProxy(transport.Session(), base + "/licence", lambda: {"X-Token": "t1"}, lambda msg: None).start()
    kodi = transport.Session()  # as ISA asks the proxy
    try:
        r = kodi.post(proxy.url, data=b"challenge", timeout=5)
        assert r.status_code == 200 and r.content == b"licence"
        r = kodi.get(proxy.url.replace("/license", "/init") + "?u=" + base + "/init.mp4", timeout=5)
        assert r.status_code == 200 and r.content.startswith(b"\x00\x00\x00\x08ftyp")
    finally:
        proxy.stop()
        server.shutdown()
        server.server_close()


def test_the_video_tracks_offered_are_logged_once_with_their_key_pairs():
    mpd, protection = rtl_layout()
    logged = []
    proxy = make_rewriter(protection, debug=logged.append)
    proxy.rewrite(mpd, MPD_URL)
    proxy.rewrite(mpd, MPD_URL)  # a live manifest's refresh: not again
    assert logged == ["video tracks offered: ? 2.5 Mbit/s pair 1; ? 2.5 Mbit/s pair 2 (dropped)", "subtitle tracks offered: none"]
    # The subtitle tracks too: language, format and role, each one.
    text = '<AdaptationSet contentType="text" lang="hun"><Role value="subtitle"/><Representation codecs="stpp"/></AdaptationSet>'
    logged = []
    proxy = make_rewriter(protection, debug=logged.append)
    proxy._log_tracks([text, text.replace("hun", "eng")], lambda aset, tag: (None,), None)
    assert logged[-1] == "subtitle tracks offered: hun stpp subtitle; eng stpp subtitle"
