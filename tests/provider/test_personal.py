"""The account's own lists and settings: parental lock, favourites, watchlist, channel order, positions, package offers."""

import base64
import collections
import json
import time

from resources.lib import provider
from resources.lib.provider import personal

Call = collections.namedtuple("Call", "path flow step method params body")


def _client(tmp_path, monkeypatch, answer):
    """A client whose calls with the login answer(path) answers; the calls made (see Call)."""
    client = provider.Client(str(tmp_path))
    calls = []

    def call(path, flow, step=None, params=None, method="GET", body=None, readd=True):
        calls.append(Call(path, flow, step, method, params, body))
        return answer(path)

    monkeypatch.setattr(client.auth, "call", call)
    return client, calls


def _parental(tmp_path, monkeypatch, pin_ok=True):
    answers = {"/setting/account/v2": {"parental_control_enabled": True}, "/setting/passcode/verify/v2": {"status": pin_ok}}
    return _client(tmp_path, monkeypatch, answers.get)


def test_the_parental_lock_flag_is_asked_once_and_kept(tmp_path, monkeypatch):
    client, calls = _parental(tmp_path, monkeypatch)
    assert client.personal.parental_lock_enabled() and client.personal.parental_lock_enabled()
    assert len(calls) == 1


def test_the_pin_goes_encrypted_with_the_startup_pages_key(tmp_path, monkeypatch):
    client, calls = _parental(tmp_path, monkeypatch)
    # A stand-in for RSA-OAEP: the key, then the message.
    monkeypatch.setattr(provider.rsaoaep, "encrypt", lambda key, message: base64.b64encode(key.encode() + message).decode())
    client.state["pin_key"] = "KEY"
    assert client.personal.verify_pin("1234")
    call = calls[-1]
    assert (call.path, call.method) == ("/setting/passcode/verify/v2", "POST")
    assert base64.b64decode(call.body["passcode"]) == b"KEY1234"


def test_a_wrong_pin_is_refused(tmp_path, monkeypatch):
    client, _ = _parental(tmp_path, monkeypatch, pin_ok=False)
    client.state["pin_key"] = "KEY"
    monkeypatch.setattr(provider.rsaoaep, "encrypt", lambda key, message: "encrypted")
    assert not client.personal.verify_pin("0000")


def test_a_favourite_channel_is_set_and_its_list_fetched_again(tmp_path, monkeypatch):
    client, calls = _client(tmp_path, monkeypatch, lambda path: {})
    (tmp_path / "channels.json").write_text(json.dumps({"favourite": {"list": []}, "subscribed": {"list": []}}))
    client.personal.set_favourite_channel("8", True)
    client.personal.set_favourite_channel(8, False)
    added, removed = calls
    assert (added.path, added.flow, added.step, added.method, added.body) == (
        "/epg/channel/favourite",
        "MY_CHANNELS",
        "SET_FAVOURITE",
        "POST",
        {"add_keys": [8]},
    )
    assert removed.body == {"delete_keys": [8]}
    assert json.loads((tmp_path / "channels.json").read_text()) == {"subscribed": {"list": []}}


def test_a_series_leaves_the_watchlist(tmp_path, monkeypatch):
    client, calls = _client(tmp_path, monkeypatch, lambda path: {"items": [{"id": "S1"}]})
    assert client.personal.watchlist() == [{"id": "S1"}]
    client.personal.set_watchlist("S1", False)
    call = calls[-1]
    assert (call.path, call.flow, call.step, call.method, call.body) == (
        "/watchlist/items",
        "MY_WATCHLIST",
        "UPDATE_WATCHLIST",
        "POST",
        {"delete_action": [{"id": "S1", "type": "series"}]},
    )


def test_the_airings_of_a_series_or_a_programme(tmp_path, monkeypatch):
    actions = {"actions": {"catchup_schedules": [{"program_id": "P"}], "schedules": []}}
    client, calls = _client(tmp_path, monkeypatch, lambda path: actions)
    assert client.personal.airings("S1") == ([{"program_id": "P"}], [])
    client.personal.airings("P1", "program")
    assert calls[-1].path == "/details/program/P1/actions/v2"


def test_the_accounts_channel_order_is_read_as_text_ids_and_kept(tmp_path, monkeypatch):
    client, calls = _client(tmp_path, monkeypatch, lambda path: {"channel_order": [18593, 18587]})
    assert client.personal.channel_order() == ["18593", "18587"] and client.personal.channel_order() == ["18593", "18587"]
    assert len(calls) == 1


def test_a_channel_order_is_saved_and_kept(tmp_path, monkeypatch):
    client, calls = _client(tmp_path, monkeypatch, lambda path: {})
    client.personal.set_channel_order(["18593", "18587"])
    call = calls[-1]
    assert (call.path, call.flow, call.step, call.body) == (
        "/epg/channel/order",
        "MY_CHANNELS",
        "SET_CHANNEL_ORDER",
        {"channel_order": [18593, 18587]},
    )
    assert client.personal.channel_order() == ["18593", "18587"] and len(calls) == 1  # kept, not fetched again


def test_an_empty_channel_order_resets_it(tmp_path, monkeypatch):
    client, calls = _client(tmp_path, monkeypatch, lambda path: {})
    client.personal.set_channel_order(["18593", "18587"])
    client.personal.set_channel_order([])
    assert calls[-1].body == {"channel_order": []} and client.personal.channel_order() == []


BOOKMARK = {"id": "18718_A_B", "time_seconds": 631, "runtime_seconds": 7920}


def test_the_positions_are_read_from_the_catch_up_bookmarks(tmp_path, monkeypatch):
    client, calls = _client(tmp_path, monkeypatch, lambda path: {"bookmarks": [BOOKMARK]})
    assert client.personal.bookmarks()[0]["time_seconds"] == BOOKMARK["time_seconds"]
    call = calls[-1]
    assert (call.path, call.flow, call.step, call.method, call.params) == (
        "/details/bookmarks/v3",
        "START_UP",
        "BOOKMARK_CATCHUP",
        "GET",
        {"type": "CATCHUP"},
    )


def test_a_position_is_saved_rounded_to_the_millisecond(tmp_path, monkeypatch):
    client, calls = _client(tmp_path, monkeypatch, lambda path: {})
    info = {"id": "18718_A_B", "program_id": "P", "media_id": "LIVE$707"}
    info.update(start_time="A", end_time="B", station_id="18718")
    client.personal.set_bookmark(info, 621.4726, 7920.0)
    call = calls[-1]
    assert (call.path, call.flow, call.step, call.method) == ("/details/bookmarks/CATCHUP/v3", "PLAYER", "SET_BOOKMARK", "PUT")
    assert call.body == dict(info, time_seconds=621.473, runtime_seconds=7920)


def test_a_programme_started_from_the_shown_list_asks_no_positions_again(tmp_path, monkeypatch):
    shown = [{"id": "a", "bookmark_type": "Catchup"}, {"id": "v", "bookmark_type": "Vod"}]
    client, calls = _client(tmp_path, monkeypatch, lambda path: {"bookmarks": shown})
    client.personal.bookmarks(details=True)  # the "Continue watching" list
    assert [b["id"] for b in client.personal.bookmarks()] == ["a"] and [c.step for c in calls] == ["BOOKMARK_ALL"]


def _browsed(tmp_path, monkeypatch):
    """A client with a watchlist, its airings and positions browsed twice; the GET calls counted."""

    def answer(path):
        back, coming = {"start_utc": "1", "description": "a long plot"}, {"start_utc": "2"}
        actions = {"catchup_schedules": [back], "schedules": [coming]}
        return {"items": [{"id": "s1"}], "bookmarks": [{"id": "b"}], "actions": actions}

    client, calls = _client(tmp_path, monkeypatch, answer)
    for _ in range(2):
        assert client.personal.watchlist() == [{"id": "s1"}]
        # Kept with the fields the plugin uses only (no plots: the state file is read by every call).
        assert client.personal.airings("s1") == ([{"start_utc": "1"}], [{"start_utc": "2"}])
        assert client.personal.bookmarks() == [{"id": "b"}]
    return client, lambda: [c.method for c in calls].count("GET")


def test_lists_browsed_again_are_kept_a_while(tmp_path, monkeypatch):
    _, gets = _browsed(tmp_path, monkeypatch)
    assert gets() == 3  # each asked once


def test_what_the_add_on_changes_itself_drops_what_was_kept(tmp_path, monkeypatch):
    client, gets = _browsed(tmp_path, monkeypatch)
    client.personal.set_watchlist("s1", False)
    client.personal.watchlist()
    client.personal.set_bookmark({"id": "b"}, 10, 100)
    client.personal.bookmarks()
    assert gets() == 5


def test_a_kept_list_is_asked_again_once_its_time_is_over(tmp_path, monkeypatch):
    client, gets = _browsed(tmp_path, monkeypatch)
    monkeypatch.setattr(time, "time", lambda: 10**10)
    client.personal.airings("s1")
    assert gets() == 4


def test_continue_watching_positions_are_deleted_with_the_fields_that_name_them(tmp_path, monkeypatch):
    client, calls = _client(tmp_path, monkeypatch, lambda path: {})
    client.state["kept"] = {"bookmarks:": {"at": 9e9, "data": []}}
    mark = {"id": "1_a_b", "runtime_seconds": 60, "program_id": "P", "bookmark_type": "Catchup", "subject_id": "S", "title": "x"}
    client.personal.delete_bookmarks([mark])
    (call,) = calls
    assert call.path == "/delete/bookmarks/v2" and call.method == "POST"
    named_by = ("id", "runtime_seconds", "program_id", "bookmark_type", "subject_id")
    assert call.body == {"bookmarks": [{k: mark[k] for k in named_by}]}
    assert "bookmarks:" not in client.state["kept"]  # the list is fetched again


def test_the_package_offers_are_read_from_a_programmes_actions():
    called = []

    class Auth:
        def call(self, path, flow, step, **kw):
            called.append(path)
            offer = {"package_name": "Package M", "price": 6990}
            return {"actions": {"channel_subscribe": [{"channel_number": "33", "channel_subscribe": [offer, offer]}]}}

    mine = personal.Personal(state={}, api=None, auth=Auth(), channels=None)
    assert [o["package_name"] for o in mine.offers("P-THIRD-PARTY")] == ["Package M"] * 2
    assert called == ["/details/program/P-THIRD-PARTY/actions/v2"]
