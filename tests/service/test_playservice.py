"""The background play service's sessions across stops and starts (Kodi stood in for, see kodistub)."""

import time
import types

import pytest

from resources.lib.service import playservice
from resources.lib.service import wakeresume
from resources.lib.util import kodienv


class Proxy:
    def __init__(self, port):
        self.base = "http://127.0.0.1:%d" % port
        self.manifest = self.base + "/manifest"
        self.stopped = False

    def serves(self, url):
        return url.startswith(self.base + "/")

    def stop(self):
        self.stopped = True


class Session:
    def __init__(self, port):
        self.id = "s%d" % port
        self.started = True
        self.switch_began = 0
        self.ticks = []
        self.proxy = Proxy(port)
        self.stream = {"channel": {"id": "c%d" % port, "media_id": "LIVE$%d" % port}, "programme": None}
        self.closed = None  # how: "all" or "asleep"

    def close(self):
        self.closed = "all"

    def sleep(self):
        self.closed = "asleep"

    def hold(self):
        pass

    def start(self):
        self.started = True

    def tick(self, player, now=None, own=True):
        self.ticks.append(own)

    def seek_to_start(self, player):
        pass


@pytest.fixture
def service(kodi, monkeypatch):
    from resources.lib import clientfactory

    # The client the service gets: a test puts its own last (see test_a_channel_list_comes_from_the_service).
    clients = [clientfactory.shared_client]
    s = playservice.PlayService(shared_client=lambda: clients[-1]()).start()
    s.clients = clients
    # Closing happens in a thread: here at once, so the test sees it.
    monkeypatch.setattr(s, "_close", lambda sessions: [x.close() for x in sessions])
    yield s
    s.stop()


def _wait(condition):
    for _ in range(100):
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_the_last_stopped_stream_sleeps_until_played_again_or_another_plays(service, monkeypatch):
    first, second, third = Session(1), Session(2), Session(3)
    service._sessions = [first, second]
    service.on_stopped()
    # The one stopped last keeps its proxy, asleep: played again by its address, it reopens the stream.
    assert first.closed == "all"
    assert _wait(lambda: second.closed == "asleep")

    # Played again through it: the sleeping proxy stays; another item: it goes.
    service._sessions = [third]
    third.started = False
    monkeypatch.setattr(service, "_playing_file", lambda: "http://127.0.0.1:2/manifest")
    service.on_started()
    assert not second.proxy.stopped and third.started
    monkeypatch.setattr(service, "_playing_file", lambda: "/some/file.mkv")
    service.on_started()
    assert second.proxy.stopped


LIST_REDRAWN = ("Container.Refresh", "builtin")


def test_a_stop_with_the_next_channel_on_its_way_keeps_its_mark(service, kodi):
    from resources.lib.service import quickplay

    coming = Session(11)
    coming.started = False
    kodi.PROPERTIES[quickplay.PLAYING] = "c11"
    service._sessions = [Session(10), coming]
    service.on_stopped()
    assert kodi.PROPERTIES.get(quickplay.PLAYING) == "c11"


def test_a_stop_beside_the_channel_list_drops_the_mark_and_redraws_the_list(service, kodi):
    from resources.lib.service import quickplay

    kodi.CONDITIONS[playservice.LIST_ON_SCREEN] = True
    kodi.PROPERTIES[quickplay.PLAYING] = "c10"
    service._sessions = [Session(10)]
    service.tick()  # as seen while it played: not on the full screen
    service.on_stopped()
    assert quickplay.PLAYING not in kodi.PROPERTIES
    assert LIST_REDRAWN in kodi.LOG


def test_a_stop_on_the_full_screen_leaves_the_list_to_kodi(service, kodi):
    from resources.lib.service import quickplay

    # Kodi loads the list itself on the way back: a second listing alongside would be one too many.
    kodi.CONDITIONS[playservice.LIST_ON_SCREEN] = True
    kodi.CONDITIONS["VideoPlayer.IsFullscreen"] = True
    kodi.PROPERTIES[quickplay.PLAYING] = "c10"
    service._sessions = [Session(10)]
    service.tick()
    service.on_stopped()
    assert quickplay.PLAYING not in kodi.PROPERTIES and LIST_REDRAWN not in kodi.LOG


def test_something_else_playing_drops_the_mark_without_a_redraw(service, kodi, monkeypatch):
    from resources.lib.service import quickplay

    service._sessions = [Session(10)]
    service.on_stopped()
    kodi.PROPERTIES[quickplay.PLAYING] = "c12"
    kodi.LOG.clear()
    monkeypatch.setattr(service, "_playing_file", lambda: "/some/file.mkv")  # a file, another add-on's stream
    service.on_started()
    assert quickplay.PLAYING not in kodi.PROPERTIES
    assert LIST_REDRAWN not in kodi.LOG


def test_stopping_the_service_stops_a_stream_it_plays(service, monkeypatch):
    stopped = []
    monkeypatch.setattr(playservice.xbmc, "executebuiltin", lambda command, wait=False: stopped.append(command))
    playing = Session(4)
    service._sessions = [playing]
    monkeypatch.setattr(service, "_playing_file", lambda: "http://127.0.0.1:4/manifest")
    service.stop()
    # Its proxy goes with the service (an update of the add-on): Kodi stops instead of waiting on it.
    assert stopped == ["PlayerControl(Stop)"] and playing.closed == "all"


def test_stopping_the_service_leaves_others_playing(service, monkeypatch):
    stopped = []
    monkeypatch.setattr(playservice.xbmc, "executebuiltin", lambda command, wait=False: stopped.append(command))
    monkeypatch.setattr(service, "_playing_file", lambda: "/some/file.mkv")
    service._sessions = [Session(5)]
    service.stop()
    assert stopped == []


def test_while_another_stream_is_on_its_way_the_playing_one_does_not_follow_the_player(service):
    playing, coming = Session(6), Session(7)
    coming.started = False
    coming.created = playservice.time.time()
    service._sessions = [playing]
    service.tick()
    service._sessions.append(coming)  # as play() adds the next channel's
    service.tick()
    # The player's position is the new one's by now: read as this one's, it was a jump back
    # that restarted the old catch-up over the channel switched to.
    assert playing.ticks == [True, False]


def test_a_live_channel_plays_again_when_kodi_wakes_up(service, monkeypatch):
    played, asked = [], []
    monkeypatch.setattr(wakeresume.threading, "Timer", lambda delay, f, args: types.SimpleNamespace(start=lambda: f(*args)))

    monkeypatch.setattr(
        service,
        "play",
        lambda cid, media, programme=None: (
            asked.append((cid, media)) or {"path": "http://p/m", "mimetype": "x", "properties": {}}
        ),
    )
    monkeypatch.setattr(service._player, "isPlaying", lambda: False, raising=False)
    monkeypatch.setattr(service._player, "play", lambda path, li: played.append(path), raising=False)
    live = Session(8)
    live.started = False
    service._sessions = [live]
    service.on_started()  # a live channel plays
    service.on_stopped()  # the TV off: Kodi stops it, then goes to sleep
    service.on_power("System.OnSleep")
    service.on_power("System.OnWake")
    assert asked == [("c8", "LIVE$8")] and played == ["http://p/m"]


def test_waking_up_after_a_programme_watched_back_plays_nothing_itself(service, monkeypatch):
    asked = []
    monkeypatch.setattr(service, "play", lambda *a, **k: asked.append(a) or {})
    back = Session(9)
    back.started = False
    back.stream["programme"] = {"start": "2026-10-26T22:20:00Z"}  # Kodi plays that again itself
    service._sessions = [back]
    service.on_started()
    service.on_stopped()
    service.on_power("System.OnSleep")
    service.on_power("System.OnWake")
    assert asked == []


class ListClient:
    """What a channel list asks of the streams' client (see channellist.view)."""

    authed = True
    synced = 0

    def sync(self):  # takes up what the plugin changed
        self.synced += 1

    def channel_list(self, scope="all", kind="all"):
        favourite = [{"id": "11", "station_id": "1001", "number": 1}]
        return favourite if scope == "favourite" else favourite + [{"id": "22", "station_id": "1002", "number": 2}]

    def channel_order(self):
        return []

    def subscribed_ids(self):
        return {"11"}

    def now_and_next(self, cache_dir):
        return {"1001": ({"description": "Híradó"}, {"description": "Sport"}), "9999": ({"description": "not listed"}, None)}


def test_a_channel_list_comes_from_the_service_over_localhost(service, monkeypatch):
    from resources.lib import parental
    from resources.lib.service import quickplay

    client = ListClient()
    service.clients.append(lambda: client)
    monkeypatch.setattr(parental, "hides_adult", lambda client: False)
    view = quickplay.ask("/list", 5, scope="all")
    assert [c["id"] for c in view["channels"]] == ["11", "22"] and client.synced == 1  # the plugin's changes taken up
    assert view["now"] == {"1001": {"description": "Híradó"}}  # only the listed channels'
    assert view["next"] == {"1001": {"description": "Sport"}}
    assert view["subscribed"] == ["11"] and view["favourites"] == ["11"] and view["ordered"] is False
    # A failure goes back as an error: the plugin then makes the list itself.
    service.clients.append(lambda: (_ for _ in ()).throw(RuntimeError("no client")))
    assert quickplay.ask("/list", 5, scope="all") == {"error": "api", "message": "no client"}


def test_without_the_service_a_list_is_not_asked_for(kodi):
    import xbmcgui

    from resources.lib.service import quickplay

    xbmcgui.Window(kodienv.HOME_WINDOW).clearProperty(playservice.PROPERTY)
    assert quickplay.ask("/list", 5, scope="all") is None


def test_a_live_channel_is_opened_again_before_its_window_ends(service, monkeypatch):
    played, asked = [], []
    monkeypatch.setattr(
        service,
        "play",
        lambda cid, media, programme=None: (
            asked.append((cid, media, programme)) or {"path": "http://p/m", "mimetype": "x", "properties": {}}
        ),
    )
    monkeypatch.setattr(service._player, "play", lambda path, li: played.append(path), raising=False)
    service._renew_live({"id": "c9", "media_id": "LIVE$9"}, "before its window ends")  # off the service's loop: on a thread
    assert _wait(lambda: played == ["http://p/m"])
    assert asked == [("c9", "LIVE$9", None)]  # live, from its edge, whatever it began as
