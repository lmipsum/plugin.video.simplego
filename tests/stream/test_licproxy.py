"""The licence proxy: licences and init segments relayed, the manifest served and refreshed, a sleeping proxy reopened."""

import email.message
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

from dashfakes import MPD_URL
from dashfakes import SPLIT_MPD
from dashfakes import Response
from dashfakes import SplitHttp

from resources.lib.net import localserver
from resources.lib.net import transport
from resources.lib.stream import licproxy
from resources.lib.stream import manifest


def test_a_refused_licence_is_reported_once_and_ends_playback():
    reported = []
    done = threading.Event()

    class Http:
        posts = 0

        def post(self, url, data=None, headers=None, timeout=None):
            Http.posts += 1

            class Response:
                status_code = 403
                content = b"<error><code>3099</code><message>refused</message></error>"
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


class _CdnHttp:
    """The CDN: the URLs in `refused` answer 404, the rest a live manifest."""

    def __init__(self, refused):
        self.refused, self.got = refused, []

    def close(self):
        pass

    def get(self, url, timeout=None):
        self.got.append(url)
        return transport.Response(404 if url in self.refused else 200, email.message.Message(), b'<MPD type="dynamic"/>', url)


def _proxy(http, logged, served=False):
    proxy = licproxy.LicenceProxy(
        http, "https://lic", {}, logged.append, manifest_url="https://cdn/1080", fallback_url="https://cdn/web"
    ).start()
    proxy.rewriter.rewrite = lambda text, url: manifest.Rewritten(text, "")
    proxy._manifest_served = served
    return proxy


def test_a_refused_full_hd_manifest_plays_the_usual_one_instead():
    http, logged = _CdnHttp({"https://cdn/1080"}), []
    proxy = _proxy(http, logged)
    try:
        assert proxy.respond(localserver.Request("GET", "/manifest", {}, b"")).status == 200
        assert http.got == ["https://cdn/1080", "https://cdn/web"]
        assert logged[0] == "manifest refused (HTTP 404): playing the fallback"
        # From then on the usual one only.
        proxy.respond(localserver.Request("GET", "/manifest", {}, b""))
        assert http.got[2:] == ["https://cdn/web"]
    finally:
        proxy.stop()


def test_a_full_hd_manifest_failing_mid_stream_is_not_swapped_under_the_player():
    http, logged = _CdnHttp({"https://cdn/1080"}), []
    proxy = _proxy(http, logged, served=True)  # already playing
    try:
        assert proxy.respond(localserver.Request("GET", "/manifest", {}, b"")).status == 502
        assert http.got == ["https://cdn/1080"]
    finally:
        proxy.stop()


def test_a_proxy_tells_its_own_addresses():
    proxy = licproxy.LicenceProxy(transport.Session(), "http://unused", {}, lambda msg: None)
    assert not proxy.serves("http://127.0.0.1:1/manifest")  # not serving yet
    proxy.start()
    try:
        assert proxy.serves(proxy.manifest) and proxy.serves(proxy.base + "/init?u=x")
        assert not proxy.serves(proxy.base + "0/manifest") and not proxy.serves("/some/file.mkv")
    finally:
        proxy.stop()


def test_a_static_manifest_is_made_once():
    class Http(SplitHttp):
        def get(self, url, headers=None, timeout=None):
            if url != MPD_URL:
                return super().get(url, headers, timeout)
            self.fetched.append(url)
            return Response(text=SPLIT_MPD, url=url)

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
