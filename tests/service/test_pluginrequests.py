"""The plugin's requests to the service: their routes and the lists answered."""

import json

from resources.lib.net import localserver
from resources.lib.service import pluginrequests


def _answer(router, method="GET", path="/list", token="t"):
    response = router.respond(localserver.Request(method, path, {"token": token, "scope": "all"}, b""))
    return response.status, json.loads(response.content)


def test_only_a_get_with_the_token_to_a_known_path_is_answered():
    router = pluginrequests.Router("t", {"/list": lambda query: {"scope": query["scope"]}})
    assert _answer(router) == (200, {"scope": "all"})
    forbidden = (403, {"error": "forbidden"})
    assert _answer(router, token="other") == forbidden
    assert _answer(router, method="POST") == forbidden
    assert _answer(router, path="/other") == forbidden


def test_a_list_that_fails_is_answered_with_what_failed(kodi):
    class Failure(Exception):
        kind = "auth"

    def failing():
        raise Failure("logged out")

    lists = pluginrequests.Lists(failing)
    assert lists.list_view("all") == {"error": "auth", "message": "logged out"}
    assert lists.menu_counts() == {"error": "auth", "message": "logged out"}
    assert pluginrequests.error_answer(RuntimeError("no client")) == {"error": "api", "message": "no client"}
