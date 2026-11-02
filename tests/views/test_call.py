"""A plugin call: how it ends for Kodi, also after it turned into another action (a picker's play)."""

from kodiside import call


def test_a_call_ends_as_the_action_it_runs_now(kodi, monkeypatch):
    import xbmcplugin

    resolved, ended = [], []
    monkeypatch.setattr(xbmcplugin, "setResolvedUrl", lambda handle, ok, li: resolved.append(ok), raising=False)
    monkeypatch.setattr(xbmcplugin, "endOfDirectory", lambda handle, succeeded=True, **kw: ended.append(succeeded), raising=False)
    listing = call("?action=continue", "3")
    listing.end(False)
    assert ended == [False] and resolved == []
    # A pick that plays: failing, Kodi is told nothing plays, else it waits 20 s and says playback failed.
    listing.redirect({"action": "play", "id": "C1"})
    listing.end(False)
    assert resolved == [False] and ended == [False]
    call("?action=play", "-1").end(False)  # no handle (a click): Kodi waits for nothing
    assert resolved == [False]


def test_a_call_makes_its_client_only_when_asked(monkeypatch):
    from resources.lib import clientfactory

    made = []
    monkeypatch.setattr(clientfactory, "make_client", lambda: made.append(1) or "client")
    menu = call("")
    assert menu.action == "root" and made == []
    assert menu.client == menu.client == "client" and made == [1]
    assert menu.url(action="channels") == "plugin://plugin.video.simplego/?action=channels"
