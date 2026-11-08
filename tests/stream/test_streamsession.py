"""A stream's session: positions, the resume question, beacons."""

import time

import pytest

from resources.lib import provider


def test_positions_are_fetched_alongside_the_session_only_for_watching_back():
    from resources.lib.stream import streamsession

    class Client:
        authed = True
        asked = 0

        def bookmarks(self):
            self.asked += 1
            raise provider.ApiError("the account's list is down")  # saved_position asks again, and says so

    client, over = Client(), {"start": "2026-10-29T13:50:00Z", "end": time.time() - 60}
    for programme in (None, {"end": time.time() + 600}, dict(over, resume=False)):  # live, restart, from the start
        assert streamsession._positions_ahead(client, programme) is None
    streamsession._positions_ahead(client, over).join()
    assert client.asked == 1
    client.authed = False
    assert streamsession._positions_ahead(client, over) is None


def test_cancelling_where_to_resume_plays_nothing_and_closes_the_session(kodi, monkeypatch):
    from resources.lib.stream import streamsession

    info = {"id": "1_2026-10-28T20:00:00Z_2026-10-28T21:00:00Z", "program_id": "P1"}
    closed = []

    class Client:
        def bookmarks(self):
            return [{"id": info["id"], "time_seconds": 600, "runtime_seconds": 3600}]

        def play_live(self, channel, programme, laps, hd=False):
            return {"session": {"session_id": "S1"}}

        def channel_of(self, channel_id):
            return None

        def beacon(self, session, complete=False):
            closed.append((session["session_id"], complete))

    client = Client()
    # Continue, from the start, or cancelled ("Back").
    kodi.ANSWERS["contextmenu"] = 0
    assert streamsession.resume_offset(client, info) == 600
    kodi.ANSWERS["contextmenu"] = 1
    assert streamsession.resume_offset(client, info) == 0
    kodi.ANSWERS["contextmenu"] = -1
    with pytest.raises(provider.CancelledError):
        streamsession.resume_offset(client, info)
    # Cancelled as the stream starts: its session, already open, is closed at once.
    monkeypatch.setattr(streamsession.parental, "gate", lambda client, channel, programme: None)
    monkeypatch.setattr(streamsession, "_positions_ahead", lambda client, programme: None)
    monkeypatch.setattr(streamsession, "programme_details", lambda client, channel, programme: None)
    monkeypatch.setattr(streamsession, "bookmark_info", lambda client, channel, programme: info)
    with pytest.raises(provider.CancelledError):
        streamsession.start_stream(client, {"id": "C1", "media_id": "M"}, {"start": "x", "end": 0})
    assert closed == [("S1", True)]


def test_the_beacon_and_the_position_are_sent_on_a_thread_and_a_busy_round_is_left_out(kodi, monkeypatch):
    """The service's loop must not wait for the provider; closing comes after the beacon on its way."""
    import threading

    from resources.lib.stream import streamsession

    release, sent = threading.Event(), []

    class Client:
        def beacon(self, session, complete=False):
            sent.append(("beacon", complete))
            if not complete:
                release.wait(5)  # a slow provider

        def set_bookmark(self, info, seconds, runtime):
            sent.append(("position", seconds))

    class Keys:
        proxy = type("Proxy", (), {"change_times": []})()

        def __init__(self, *args, **kwargs):
            pass

        def follow(self, *args):
            pass

        def close(self, keep=None):
            pass

    class Player:
        def isPlaying(self):
            return True

        def getTime(self):
            return 120.0

        def getTotalTime(self):
            return 3600.0

    monkeypatch.setattr(streamsession.keyfollower, "KeyFollower", Keys)
    stream = {"session": {"session_id": "S1", "interval": 60}, "channel": {"id": "C1"}, "bookmark": {"id": "B"}}
    session = streamsession.Session(Client(), stream, proxy=None)
    started = time.time()
    session.tick(Player(), now=session.created + 61)  # the position and the beacon due
    assert time.time() - started < 1
    session.tick(Player(), now=session.created + 122)  # due again, but the last round is still sending
    release.set()
    session.close()
    assert sent == [("position", 120.0), ("beacon", False), ("position", 120.0), ("beacon", True)]
