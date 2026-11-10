"""The phone login: one QR code at a time, so a second press while the first is coming up is ignored."""

import contextlib

from resources.lib.login import phonelogin


def test_a_second_login_while_one_is_running_opens_no_qr_window(kodi, monkeypatch):
    opened = []
    monkeypatch.setattr(phonelogin, "_phone_login", lambda client, timeout: opened.append("opened") or "token")
    assert phonelogin.wait_for_token(client=object()) == "token"
    assert opened == ["opened"]
    kodi.PROPERTIES[phonelogin.IN_PROGRESS] = "1"  # another plugin call is still running its own login
    assert phonelogin.wait_for_token(client=object()) is None
    assert opened == ["opened"]  # the second start did nothing


def test_the_running_flag_is_cleared_even_after_a_failed_login(kodi, monkeypatch):
    def boom(client, timeout):
        raise RuntimeError("provider down")

    monkeypatch.setattr(phonelogin, "_phone_login", boom)
    with contextlib.suppress(RuntimeError):
        phonelogin.wait_for_token(client=object())
    assert phonelogin.IN_PROGRESS not in kodi.PROPERTIES  # a next start works
