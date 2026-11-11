"""The login: a refused token renewed, a removed device attached again, each once."""

import time

import pytest
from providerfakes import Answer
from providerfakes import FakeApi
from providerfakes import StsHttp

from resources.lib import provider
from resources.lib.provider import auth
from resources.lib.provider import core
from resources.lib.provider import statefile

REMOVED = Answer(401, text="This device was removed")


def _login(tmp_path, answers):
    """A logged-in Auth whose calls answer these responses in turn; the API and the token renewal it uses."""
    state = statefile.State(str(tmp_path / core.STATE_FILE))
    state.update(refresh_token="r", access_token="t", access_expires=time.time() + 3600)
    sts = StsHttp()
    tenant = {"refresh_login_url": "https://sts.example/refresh?token=${refreshToken}&to=${redirectUri}"}
    api = FakeApi(state, sts, answers, guest=lambda path, params: tenant)
    return auth.Auth(state, api), api, sts


def test_a_refused_token_is_renewed_and_the_call_made_again(tmp_path):
    login, api, sts = _login(tmp_path, [Answer(401), Answer(data={"ok": True})])
    assert login.call("/x", "F") == {"ok": True}
    assert [path for path, _ in api.sent] == ["/x", "/x"] and sts.renewals == 1
    assert login.valid_access_token() == "new"


def test_a_token_refused_after_its_renewal_is_given_up(tmp_path):
    login, _, sts = _login(tmp_path, [Answer(401), Answer(401)])
    with pytest.raises(provider.AuthError):
        login.call("/x", "F")  # no third try
    assert sts.renewals == 1


def test_a_removed_device_is_attached_again_once_and_what_was_its_forgotten(tmp_path):
    account = Answer(data={"channelMap_id": "7"})
    login, api, _ = _login(tmp_path, [REMOVED, account, Answer(data={"ok": True})])
    forgotten = []
    login.on_device_readded(lambda: forgotten.append("registration"))
    assert login.call("/x", "F") == {"ok": True}
    assert api.sent == [("/x", None), ("/user/account", {"fresh_login": "true"}), ("/x", None)]
    assert forgotten == ["registration"]


def test_a_refused_attaching_call_is_given_up(tmp_path):
    login, api, _ = _login(tmp_path, [REMOVED])
    with pytest.raises(provider.AuthError):
        login.valid_account(force=True, fresh_login=True)
    assert [path for path, _ in api.sent] == ["/user/account"]


def test_a_call_that_must_not_attach_the_device_is_given_up(tmp_path):
    login, api, _ = _login(tmp_path, [REMOVED])
    with pytest.raises(provider.AuthError):
        login.call("/setting/devices/d", "F", method="DELETE", readd=False)
    assert [path for path, _ in api.sent] == ["/setting/devices/d"]
