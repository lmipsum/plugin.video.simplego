from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

import pytest

from resources.lib.login import loginserver

TOKEN_URL = "https://player.telekomtvgo.hu/robots.txt?oauth=x&access_token=AAA&refresh_token=aaaa.bbbb.cccc"


@pytest.fixture
def receiver():
    r = loginserver.LoginReceiver("https://login.example/", {name: "<%s>" % name for name in loginserver.TEXT_IDS}, "en", port=0)
    yield r
    r.stop()


def status(url, data=None, ctype="application/x-www-form-urlencoded"):
    try:
        return urlopen(Request(url, data=data, headers={"Content-Type": ctype}), timeout=5).status
    except HTTPError as e:
        return e.code


def base(r):
    return "http://127.0.0.1:%d" % r.port


def test_page_needs_the_code(receiver):
    assert status(base(receiver) + "/") == 403
    assert status(base(receiver) + "/?c=wrong") == 403
    assert status(receiver.phone_url("127.0.0.1")) == 200


def test_the_page_is_in_the_texts_given_escaped(receiver):
    page = urlopen(receiver.phone_url("127.0.0.1"), timeout=5).read().decode()
    assert '<html lang="en">' in page and "&lt;button&gt;" in page and "<button>" not in page.replace("<button type", "")


def test_form_post(receiver):
    form = lambda token, code=receiver.code: urlencode({"code": code, "token": token}).encode()  # noqa: E731
    assert status(base(receiver) + "/login", form(TOKEN_URL, code="0")) == 403
    # The usual slip: the robots.txt text instead of the page address.
    assert status(base(receiver) + "/login", form("User-agent: *\nDisallow: /")) == 400
    assert receiver.token is None
    assert status(base(receiver) + "/login", form(TOKEN_URL)) == 200
    assert receiver.token == TOKEN_URL
