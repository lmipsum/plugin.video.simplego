"""The add-on's own small HTTP servers: an app gets each request, its answer goes back as given."""

from resources.lib.net import localserver
from resources.lib.net import transport


def test_an_app_answers_gets_and_posts_with_their_query_and_body():
    seen = []

    def app(request):
        seen.append(request)
        return localserver.Response(201, b"answer", "text/plain", [("X-Kept", "yes")])

    server = localserver.start(app, request_timeout=5)
    try:
        base = "http://127.0.0.1:%d" % localserver.port(server)
        http = transport.Session()
        r = http.get(base + "/path?a=1&a=2&b=x%20y", timeout=5)
        assert r.status_code == 201 and r.content == b"answer" and r.headers.get("X-Kept") == "yes"
        http.post(base + "/post", data=b"body", timeout=5)
    finally:
        localserver.stop(server)
    # The first value of each parameter; the path without the query; a GET's body empty.
    assert seen == [
        localserver.Request("GET", "/path", {"a": "1", "b": "x y"}, b""),
        localserver.Request("POST", "/post", {}, b"body"),
    ]
