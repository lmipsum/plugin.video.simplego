"""The client's HTTP on the standard library (provider.transport), against a local server."""

import gzip
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

import pytest

from resources.lib.net import transport


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # kept connections, as the provider's servers do
    posts = []  # the paths POSTed, in order

    def do_GET(self):
        if self.path.startswith("/bye"):
            # Answered as a kept connection, then closed: an idle connection the server dropped.
            self._send(200, b"bye", {})
            self.close_connection = True
        elif self.path.startswith("/redirect"):
            self._send(302, b"", {"Location": "/landed?from=redirect"})
        elif self.path.startswith("/gzip"):
            self._send(200, gzip.compress(b'{"zipped": true}'), {"Content-Encoding": "gzip"})
        elif self.path.startswith("/range"):
            self._send(206, b"0123456789"[:4], {"Content-Range": "bytes 0-3/10"})
        elif self.path.startswith("/brokengzip"):
            self._send(200, b"not gzip at all", {"Content-Encoding": "gzip"})
        elif self.path.startswith("/missing"):
            self._send(404, b"no", {})
        elif self.path.startswith("/away"):
            self._send(302, b"", {"Location": self.headers.get("X-Other") + "/landed"})
        elif self.path.startswith("/cookies"):
            self._send(200, b"x", {"Set-Cookie": "deviceId=d1; Path=/"}, extra=[("Set-Cookie", "sessionId=s1; HttpOnly")])
        else:
            echo = {
                "path": self.path,
                "ua": self.headers.get("User-Agent"),
                "port": self.client_address[1],
                "auth": self.headers.get("Authorization"),
                "range": self.headers.get("Range"),
            }
            self._send(200, json.dumps(echo).encode(), {"Content-Type": "application/json; charset=utf-8"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        Handler.posts.append(self.path)
        if self.path.startswith("/drop"):
            # Taken, then the connection closed with no answer: was it handled? The client can't tell.
            self.close_connection = True
            return
        echo = {"body": body.decode(), "type": self.headers.get("Content-Type"), "path": self.path}
        self._send(201, json.dumps(echo).encode(), {})

    def _send(self, status, body, headers, extra=()):
        self.send_response(status)
        for name, value in list(headers.items()) + list(extra):
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % s.server_address[1]
    s.shutdown()
    s.server_close()


class Failed(Exception):
    pass


def test_get_with_query_headers_and_json(server):
    session = transport.Session(error=Failed)
    session.headers["User-Agent"] = "Simple GO"
    r = session.get(server + "/x?a=1", params={"b": "2 3"}, timeout=5)
    assert r.ok and r.status_code == 200
    assert r.json()["path"] == "/x?a=1&b=2+3" and r.json()["ua"] == "Simple GO"
    assert r.headers.get("content-type").startswith("application/json")  # any case


def test_post_json_and_raw_body(server):
    session = transport.Session(error=Failed)
    r = session.post(server + "/p", json={"a": 1}, timeout=5)
    assert r.status_code == 201 and json.loads(r.json()["body"]) == {"a": 1} and r.json()["type"] == "application/json"
    r = session.request("POST", server + "/p", data="raw", headers={"Content-Type": "text/plain"}, timeout=5)
    assert r.json()["body"] == "raw" and r.json()["type"] == "text/plain"


def test_redirects_followed_or_not(server):
    session = transport.Session(error=Failed)
    assert session.get(server + "/redirect", timeout=5).json()["path"] == "/landed?from=redirect"
    r = session.get(server + "/redirect", allow_redirects=False, timeout=5)  # as the login's renewal walks them
    assert r.status_code == 302 and r.headers.get("Location") == "/landed?from=redirect"


def test_gzip_and_cookies(server):
    session = transport.Session(error=Failed)
    assert session.get(server + "/gzip", timeout=5).json() == {"zipped": True}
    assert session.get(server + "/cookies", timeout=5).cookies.get_dict() == {"deviceId": "d1", "sessionId": "s1"}


def test_connections_are_kept_and_shared_by_threads(server):
    session = transport.Session(error=Failed)
    ports = {session.get(server + "/k", timeout=5).json()["port"] for _ in range(3)}
    assert len(ports) == 1  # one kept connection, one after the other
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(session.get(server + "/t", timeout=5).ok)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert answers == [True] * 5
    session.close()


def test_a_kept_connection_the_server_closed_is_not_used(server):
    session = transport.Session(error=Failed)
    first = session.get(server + "/k", timeout=5).json()["port"]
    assert session.get(server + "/bye", timeout=5).text == "bye"  # on the same connection, then dropped
    time.sleep(0.2)  # the server's close reaching the idle socket
    Handler.posts.clear()
    r = session.post(server + "/p", json={"a": 1}, timeout=5)  # not a request worth repeating
    assert r.status_code == 201 and Handler.posts == ["/p"]
    assert session.get(server + "/k", timeout=5).json()["port"] != first


def test_a_post_the_server_may_have_taken_is_not_sent_again(server):
    session = transport.Session(error=Failed)
    session.get(server + "/k", timeout=5)  # a kept connection the POST goes on
    Handler.posts.clear()
    with pytest.raises(Failed):
        session.post(server + "/drop", json={"a": 1}, timeout=5)
    assert Handler.posts == ["/drop"]  # once: a second stream session would count against the limit


def test_an_error_status_names_no_query(server):
    with pytest.raises(Failed) as e:
        transport.Session(error=Failed).get(server + "/missing?token=SECRET", timeout=5).raise_for_status()
    assert "404" in str(e.value) and "/missing" in str(e.value) and "SECRET" not in str(e.value)


def test_a_network_failure_is_the_given_error():
    with pytest.raises(Failed):
        transport.Session(error=Failed).get("http://127.0.0.1:1/", timeout=5)


def test_error_statuses_and_ranges(server):
    session = transport.Session(error=Failed)
    r = session.get(server + "/missing", timeout=5)
    assert not r.ok and r.status_code == 404
    with pytest.raises(Failed):
        r.raise_for_status()
    r = session.get(server + "/range", headers={"Range": "bytes=0-3"}, timeout=5)
    assert r.ok and r.status_code == 206 and r.content == b"0123"
    r.raise_for_status()  # 206 is fine


def test_a_broken_gzip_body_is_the_given_error(server):
    with pytest.raises(Failed):
        transport.Session(error=Failed).get(server + "/brokengzip", timeout=5)


def test_the_url_after_redirects(server):
    assert transport.Session().get(server + "/redirect", timeout=5).url == server + "/landed?from=redirect"


def test_private_headers_stay_with_their_host(server):
    other = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        other_url = "http://localhost:%d" % other.server_address[1]  # another host name, the same machine
        session = transport.Session()
        same = session.get(server + "/redirect", headers={"Authorization": "secret"}, timeout=5)
        assert same.json()["auth"] == "secret"  # the same host: kept
        away = session.get(server + "/away", headers={"Authorization": "secret", "X-Other": other_url}, timeout=5)
        assert away.url == other_url + "/landed" and away.json()["auth"] is None
    finally:
        other.shutdown()
        other.server_close()


def test_usable_after_close_and_from_many_threads(server):
    session = transport.Session()
    session.get(server + "/a", timeout=5)
    session.close()
    assert session.get(server + "/b", timeout=5).ok
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(session.get(server + "/c", timeout=5).ok)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert answers == [True] * 8


def test_one_tls_context_per_ca_bundle_in_a_process():
    first, second = transport.Session(), transport.Session()
    assert first._ssl() is second._ssl()
    other = transport.Session()
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    other.verify = os.path.join(root, "resources", "certs", "intermediate.crt")  # another CA bundle
    assert other._ssl() is not first._ssl()
