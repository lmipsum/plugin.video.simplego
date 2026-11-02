"""Playing in the plugin itself, when the service cannot: the stream handed to Kodi, its session kept."""

import pytest
from kodiside import call

from resources.lib.login import phonelogin
from resources.lib.views import play as views_play


class Account:
    logged_in = True

    def __init__(self):
        self.calls = []

    def is_logged_in(self):
        return self.logged_in

    def channel_list(self):
        return [{"id": "C1", "media_id": "M1"}]

    def login_with_refresh_token(self, token):
        self.calls.append(("login", token))

    def close_stale_sessions(self, keep):
        self.calls.append(("close stale", keep))


class Session:
    """A stream's session: what the plugin did with it, in order."""

    id = "S1"

    def __init__(self, client, stream, proxy):
        self.done = []
        Session.last = self

    def start(self):
        self.done.append("start")

    def seek_to_start(self, player):
        self.done.append("seek")

    def tick(self, player):
        self.done.append("tick")

    def close(self):
        self.done.append("close")


@pytest.fixture
def play(kodi, monkeypatch):
    import types

    import xbmcplugin

    from resources.lib import resolveditem
    from resources.lib.stream import playitem
    from resources.lib.stream import streamsession

    started = []
    resolved = []
    proxy = types.SimpleNamespace(manifest="http://127.0.0.1/m.mpd", url="http://127.0.0.1/licence")

    def start_stream(client, channel, programme):
        started.append((channel, programme))
        return {"type": "dash"}, proxy

    monkeypatch.setattr(streamsession, "start_stream", start_stream)
    monkeypatch.setattr(streamsession, "Session", Session)
    monkeypatch.setattr(playitem, "spec", lambda stream, manifest, licence, major: {"path": manifest})
    monkeypatch.setattr(resolveditem, "list_item", lambda spec: spec["path"])
    monkeypatch.setattr(xbmcplugin, "setResolvedUrl", lambda handle, ok, li: resolved.append((ok, li)), raising=False)
    # Android with InputStream Adaptive: InputStream Helper has nothing to check.
    kodi.CONDITIONS["System.Platform.Android"] = True
    kodi.CONDITIONS["System.AddonIsEnabled(inputstream.adaptive)"] = True

    def make(query):
        client = Account()
        p = views_play.PlayViews(call(query, client=client))
        p.client, p.started_streams, p.resolved = client, started, resolved  # what the tests look at
        return p

    return make


def test_a_live_play_hands_kodi_the_stream_and_marks_its_channel(play, kodi):
    from resources.lib.service import quickplay

    p = play("?action=play&id=C1&media=M1")
    p.do_play()
    assert p.started_streams == [({"id": "C1", "media_id": "M1"}, None)]  # no channel list fetched
    assert p.resolved == [(True, "http://127.0.0.1/m.mpd")]
    assert kodi.PROPERTIES[quickplay.PLAYING] == "C1"
    assert p.client.calls == [("close stale", "S1")]
    assert Session.last.done == ["close"]  # nothing started playing: the session is closed


def test_a_catch_up_play_marks_no_channel(play, kodi):
    from resources.lib.service import quickplay

    p = play("?action=play&id=C1&stream=M1&programme=2026-10-30T20:00:00Z~2026-10-30T20:45:00Z~ct")
    p.do_play()
    assert p.started_streams[0][0] == {"id": "C1", "media_id": "M1"}  # IPTV Simple's "stream"
    assert p.started_streams[0][1] is not None
    assert kodi.PROPERTIES[quickplay.PLAYING] == ""


def test_a_channel_without_its_media_is_found_in_the_list(play):
    p = play("?action=play&id=C1")
    p.do_play()
    assert p.started_streams == [({"id": "C1", "media_id": "M1"}, None)]
    with pytest.raises(Exception, match="Unknown channel C9"):
        play("?action=play&id=C9").do_play()


def test_desktop_kodi_is_refused_before_anything(play, kodi):
    from resources.lib import provider

    kodi.CONDITIONS["System.Platform.Windows"] = True
    p = play("?action=play&id=C1&media=M1")
    with pytest.raises(provider.LicenceRefusedError):
        p.do_play()
    assert p.started_streams == []


def test_logged_out_it_logs_in_by_phone_first(play, monkeypatch):
    p = play("?action=play&id=C1&media=M1")
    p.client.logged_in = False
    monkeypatch.setattr(phonelogin, "wait_for_token", lambda client: None)
    p.do_play()  # the login window closed: nothing plays
    assert p.started_streams == [] and [ok for ok, li in p.resolved] == [False]
    monkeypatch.setattr(phonelogin, "wait_for_token", lambda client: "token")
    from resources.lib.login import loginstate

    monkeypatch.setattr(loginstate, "login_changed", lambda: None)
    p.do_play()
    assert ("login", "token") in p.client.calls and len(p.started_streams) == 1


def test_the_session_is_kept_while_our_stream_plays_then_closed(play, monkeypatch):
    import xbmc

    from resources.lib.views import play as views_play

    class Player:
        answers = [True, True, False]  # found playing, playing at the first tick, then stopped

        def isPlaying(self):
            return self.answers.pop(0)

        def getPlayingFile(self):
            return "http://127.0.0.1/m.mpd"

    monkeypatch.setattr(views_play.xbmc, "Player", Player)
    assert views_play.xbmc is xbmc
    play("?action=play&id=C1&media=M1").do_play()
    assert Session.last.done == ["start", "seek", "tick", "close"]
