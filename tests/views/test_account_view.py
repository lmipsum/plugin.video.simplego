"""The account's views: logging in and out, the devices list, the parental lock."""

import pytest
from kodiside import call

from resources.lib.login import phonelogin
from resources.lib.views import account as views_account


def test_the_device_list_marks_this_device_and_tells_set_top_boxes_apart(kodi):
    class Me:
        device_id = "me"

    assert views_account.device_label(Me(), {"id": "me", "name": "Kodi"}) == "[COLOR grey]Kodi - This device[/COLOR]"
    assert views_account.device_label(Me(), {"id": "p", "name": "Phone"}) == "Phone"
    # The provider's set-top boxes are left out of the device list (see do_devices).
    assert views_account.is_stb({"id": "b", "name": "Smartbox", "device_type": "AndroidStb"})


class Account:
    """A logged-in account: this Kodi, a phone and a set-top box among its devices."""

    device_id = "me"

    def __init__(self):
        self.calls = []
        self.listed = [
            {"id": "me", "name": "Kodi"},
            {"id": "p", "name": "Phone"},
            {"id": "b", "name": "Smartbox", "device_type": "AndroidStb"},
        ]

    def devices(self):
        return list(self.listed)

    def remove_device(self, device_id):
        self.calls.append(("remove", device_id))
        self.listed = [d for d in self.listed if d["id"] != device_id]

    def logout(self):
        self.calls.append(("logout",))

    def login_url(self):
        return "https://login.example/"

    def login_with_refresh_token(self, token):
        self.calls.append(("login", token))

    def parental_lock_enabled(self):
        return True

    def verify_pin(self, pin):
        return pin == "1234"


@pytest.fixture
def views(kodi, monkeypatch):
    from resources.lib.login import loginstate

    changes = []
    monkeypatch.setattr(loginstate, "login_changed", lambda: changes.append("login"))
    monkeypatch.setattr(loginstate, "show_account", lambda client, fresh=False: changes.append("account"))
    client = Account()
    views = views_account.AccountViews(call("?action=logout", "-1", client=client))
    views.client, views.changes = client, changes  # what the tests look at afterwards
    return views


def test_logging_out_is_asked_first(views, kodi):
    views.do_logout()
    assert views.client.calls == [] and views.changes == []  # answered no
    kodi.ANSWERS["yesno"] = True
    views.do_logout()
    assert views.client.calls == [("logout",)] and views.changes == ["login"]
    assert ("Container.Refresh", "builtin") in kodi.LOG


def test_a_phone_login_logs_in_and_says_so(views, kodi, monkeypatch):
    monkeypatch.setattr(phonelogin, "wait_for_token", lambda client: "token")
    views.do_login()
    assert views.client.calls == [("login", "token")] and views.changes == ["login"]
    assert (kodi.STRINGS[30022], "notification") in kodi.LOG


def test_a_closed_login_window_logs_nobody_in(views, kodi, monkeypatch):
    monkeypatch.setattr(phonelogin, "wait_for_token", lambda client: None)
    views.do_login()
    assert views.client.calls == [] and views.changes == []


def test_the_login_window_waits_for_the_phone_then_cleans_up(views, kodi, monkeypatch):
    import xbmcgui

    from resources.lib.login import loginserver
    from resources.lib.login import qrwindow

    stopped, labels = [], []

    class Receiver:
        token = "from the phone"

        def __init__(self, login_url, texts, lang=""):
            assert login_url == "https://login.example/" and set(texts) == set(loginserver.TEXT_IDS)

        def phone_url(self, ip):
            return "http://%s:1234/x" % ip

        def stop(self):
            stopped.append(True)

    def label(*args, **kwargs):
        labels.append(args[4])
        return xbmcgui.ListItem()

    monkeypatch.setattr(loginserver, "LoginReceiver", Receiver)
    monkeypatch.setattr(qrwindow, "make_qr_png", lambda text, path: open(path, "wb").close())
    monkeypatch.setattr(xbmcgui, "ControlLabel", label)
    assert phonelogin.wait_for_token(views.client) == "from the phone"
    assert stopped == [True]
    # Colours by Kodi's colour names, not hex: a skin can set them.
    assert labels[1] == "[COLOR %s]http://127.0.0.1:1234/x[/COLOR]" % qrwindow.URL_COLOUR
    assert labels[0].startswith("[COLOR %s]" % qrwindow.TITLE_COLOUR)


def test_the_device_list_removes_other_devices_only(views, kodi):
    # This Kodi (row 0) cannot be removed; the phone (row 1) can, once confirmed; then closed.
    kodi.ANSWERS["select"] = [0, 1, -1]
    kodi.ANSWERS["yesno"] = True
    views.do_devices()
    assert views.client.calls == [("remove", "p")] and views.changes == ["account"]
    assert (kodi.STRINGS[30037], "notification") in kodi.LOG


def test_the_parental_lock_needs_the_pin_then_saves_and_exports(views, kodi, lock_settings):
    kodi.ANSWERS["numeric"] = "0000"  # wrong
    views.do_parental()
    assert lock_settings.settings() == lock_settings.DEFAULTS
    kodi.ANSWERS["numeric"] = "1234"
    kodi.ANSWERS["select"] = lock_settings.AGES.index(16)
    kodi.ANSWERS["yesno"] = [False, True]  # unrated: open; adult channels: shown
    views.do_parental()
    assert lock_settings.settings() == {"age": 16, "unrated": False, "adult": True}
    assert kodi.PROPERTIES[views_account.kodiutil.EXPORT_REQUEST] == "1"
