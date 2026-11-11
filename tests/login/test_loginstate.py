"""The login's state as the settings show it."""

import time

from resources.lib.login import loginstate


class AccountClient:
    """A logged-in account whose login runs out in `days`."""

    def __init__(self, days, logged_in=True):
        self.expires = int(time.time() + days * 24 * 3600)
        self.logged_in = logged_in
        self.forced = []
        self.info = {
            "email": "user@example.com",
            "current_logged_in_devices": 2,
            "max_device_allowed": 5,
            "account_type": "MULTISCREEN_2022",
            "catchup_enabled": True,
            "timeshift_enabled": False,
        }

    def valid_account(self, force=False):
        self.forced.append(force)
        return self.info

    def login_expires(self):
        return self.expires

    def is_logged_in(self):
        return self.logged_in


def test_the_account_rows_show_the_login_devices_subscription_and_services(kodi):
    client = AccountClient(days=300)
    loginstate.show_account(client, fresh=True)
    expires = time.strftime("%Y-%m-%d", time.localtime(client.expires))
    assert kodi.SETTINGS["account_login"] == "valid until %s" % expires
    assert kodi.SETTINGS["devices"] == "2 / 5"
    assert kodi.SETTINGS["account_subscription"] == "MULTISCREEN_2022"
    assert kodi.SETTINGS["account_catchup"] is True and not kodi.SETTINGS.get("account_timeshift")
    assert not kodi.SETTINGS.get("account_recording")
    assert client.forced == [True]


def test_the_login_running_out_is_warned_of(kodi):
    loginstate.warn_if_login_runs_out(AccountClient(days=300))
    loginstate.warn_if_login_runs_out(AccountClient(days=3, logged_in=False))
    assert not [m for m, level in kodi.LOG if level == "notification"]
    loginstate.warn_if_login_runs_out(AccountClient(days=3))
    assert [m for m, level in kodi.LOG if level == "notification"][0].startswith("Your login runs out on ")


def test_a_login_marks_the_login_changed_and_shows_the_given_clients_state(kodi):
    from resources.lib import kodiutil

    client = AccountClient(days=300)
    client.authed = False  # a guest still: no account rows asked
    loginstate.login_changed(client)
    assert kodiutil.home().getProperty(kodiutil.LOGIN_CHANGED) == "1" and kodi.SETTINGS["logged_in"] is True
    kodiutil.home().clearProperty(kodiutil.LOGIN_CHANGED)
