"""The channel lists: kept in a file every client shares, the subscription when the server cannot say."""

import json

from providerfakes import FakeApi
from providerfakes import FakeAuth

from resources.lib import provider
from resources.lib.provider import auth
from resources.lib.provider import channels
from resources.lib.provider import core
from resources.lib.provider import statefile
from resources.lib.util import sharedfile


def test_an_unknown_subscription_lets_the_server_decide(tmp_path):
    def down(path, params):
        raise provider.ApiError("down")

    state = statefile.State(str(tmp_path / "session.json"))
    login = FakeAuth(down)
    lists = channels.Channels(state, None, login, sharedfile.SharedJson(str(tmp_path / "channels.json"), state.lock))
    assert lists.subscribed_ids() is None
    login.authed = False  # no login: no subscription to know
    assert lists.subscribed_ids() is None


def test_the_channel_lists_are_kept_in_their_own_file_every_client_shares(tmp_path):
    lists = {"subscribed": {"list": [{"id": "1"}]}, "favourite": {"list": [{"id": "2"}]}}
    (tmp_path / "session.json").write_text(json.dumps({"channels_cache": lists, "device_id": "d"}))
    (tmp_path / "channels.json").write_text(json.dumps(lists))
    first, second = provider.Client(str(tmp_path)), provider.Client(str(tmp_path))
    assert second.channel_of("2") == {"id": "2"}
    # Up to 0.8.150 the lists were in the state: that copy goes, the rest of the state stays.
    assert json.loads((tmp_path / "session.json").read_text()) == {"device_id": "d"}
    first.channels.forget("favourite")
    assert second.channel_of("2") is None  # another client's change taken up
    assert second.channel_of("1") == {"id": "1"}
    second.logout()  # the next account's lists are its own
    assert first.channel_of("1") is None
    assert json.loads((tmp_path / "session.json").read_text()) == {"device_id": "d"}


def test_guest_mode_keeps_the_public_channel_list(tmp_path):
    asked = []

    def guest_call(path, params):
        asked.append(path)
        return {"channels": [], "serviceCollection_service_map": {}, "services_map": {}}

    state = statefile.State(str(tmp_path / core.STATE_FILE))  # never logged in
    api = FakeApi(state, guest=guest_call)  # nothing sent with a login: no answers for it
    login = auth.Auth(state, api)
    assert not login.authed
    kept = sharedfile.SharedJson(str(tmp_path / "channels.json"), state.lock)
    channels.Channels(state, api, login, kept).list(scope="subscribed")  # no subscription without a login: the public list
    assert asked == ["/epg/channel"]
    assert "guest" in json.loads((tmp_path / "channels.json").read_text()) and api.sent == []
