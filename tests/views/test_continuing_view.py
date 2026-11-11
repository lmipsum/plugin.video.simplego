"""Continue watching: the rows and a row's click."""

from kodiside import G
from kodiside import continue_at

from resources.lib import clientfactory
from resources.lib import kodiutil
from resources.lib.data import channellist
from resources.lib.util import localtime
from resources.lib.views import listing


def test_continue_watching_rows_show_the_programme_its_episode_poster_and_length(kodi, monkeypatch, tmp_path):
    import xbmcplugin

    from resources.lib import plugin
    from resources.lib.data import infopages

    continue_at(monkeypatch, tmp_path)
    monkeypatch.setattr(localtime, "local_date", lambda stamp: "2026.11.04.")

    added = []
    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append(li), raising=False)
    pages = {("program", "F-1"): {"type": "movie", "year": 2017}, ("program", "AB-1"): {"type": "series", "year": 2010}}
    kept = lambda client, keys, out_dir, full=True: {k: pages[k] for k in keys if k in pages}  # noqa: E731
    monkeypatch.setattr(infopages, "pages_for", kept)
    channel = {"id": "C1", "media_id": "M", "name": "M1", "logo": "logo.png"}
    monkeypatch.setattr(channellist, "by_station", lambda client: {"1": channel})

    class Client:
        def bookmarks(self, details=False):
            mark = {"id": "1_2026-10-28T20:00:00Z_2026-10-28T21:00:00Z", "title": "Sorozat", "program_id": "AB-1"}
            film = dict(mark, id="1_2026-10-28T21:00:00Z_2026-10-28T23:00:00Z", title="Tűnj el!", program_id="F-1")
            film.update(time_seconds=600, runtime_seconds=7200)
            return [dict(mark, season_number=2, episode_number=5, time_seconds=600, runtime_seconds=3600), film]

        def airings(self, item_id, kind="series"):
            # The film's airing still on catch-up, the episode's not any more.
            if item_id == "F-1":
                return [{"station_id": "1", "start_utc": "2026-10-28T21:00:00Z"}], []
            return [{"station_id": "1", "start_utc": "2026-10-21T20:00:00Z"}], []

    monkeypatch.setattr(clientfactory, "make_client", Client)
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", "?action=continue"]).run()
    tag = added[0].getVideoInfoTag()
    assert tag["MediaType"] == "episode" and (tag["Season"], tag["Episode"]) == (2, 5)
    assert tag["Studios"] == ["M1"] and tag["Duration"] == 3600 and tag["VideoStream"] == {"duration": 3600}
    assert added[0].art["poster"].endswith("/program/ab-1/2x3/keyartxlarge.jpg")  # the side panel: the programme's
    # One line: the programme (its episode); no logo, no channel. No date: when it leaves catch-up varies by channel.
    assert added[0].label == "Sorozat" + G % " | S2E5"
    assert "ProductionCode" not in added[0].getVideoInfoTag()
    # Whether each (greyed ones too) is still on catch-up by its programme's airings: logged only, until shown right.
    logged = [m for m, _ in kodi.LOG if m.startswith("[plugin.video.simplego] catch-up of")]
    assert len(logged) == 2 and "(Sorozat, active): gone" in logged[0] and "(Tűnj el!, active): on" in logged[1]
    # Kodi's own favourites item off, ours in its words.
    assert all(li.properties["hide_add_remove_favourite"] == "true" for li in added)
    assert "icon" not in added[0].art
    assert added[1].label == "Tűnj el! (2017)"  # a film's year after its title (from its info page)
    film = added[1].getVideoInfoTag()
    assert film["MediaType"] == "movie" and film["Year"] == 2017  # the info page puts it after the title
    # The 16:9 picture as background; no thumb, else Estuary's info page puts the poster over itself.
    for li in added:
        assert "thumb" not in li.art and li.art["fanart"].endswith("/16x9/keyartxlarge.jpg")
        # An action opening the picker (see the next test), its resume point kept for the row's icon.
        assert li.properties["IsPlayable"] == "false" and li.getVideoInfoTag()["ResumePoint"]


def test_a_continue_watching_row_resumes_plays_from_the_beginning_or_resets_its_position(kodi, monkeypatch, tmp_path):
    """A click: Kodi's resume question in its own words, plus resetting the position (deleting it)."""
    import xbmcgui

    from resources.lib import plugin
    from resources.lib.service import quickplay

    continuelist = continue_at(monkeypatch, tmp_path)

    mark = {"id": "1_2026-10-28T20:00:00Z_2026-10-28T21:00:00Z", "program_id": "AB-1", "runtime_seconds": 3600}
    calls, ran, asked = [], [], []

    class Client:
        def bookmarks(self, details=False):
            return [dict(mark, title="Film", time_seconds=985, bookmark_type="Catchup")]

        def delete_bookmarks(self, bookmarks):
            calls.append(("delete", [b["id"] for b in bookmarks]))
            if fail:
                raise plugin.provider.ApiError("refused")

        def set_bookmark(self, info, seconds, runtime):
            calls.append(("set", info["id"], info["station_id"], seconds, runtime))

    monkeypatch.setattr(clientfactory, "make_client", Client)
    monkeypatch.setattr(kodiutil, "kodi_setting", lambda setting, default=None: listing.SELECT_PLAY)
    monkeypatch.setattr(kodi.xbmc, "executebuiltin", lambda command, wait=False: ran.append(command))
    menus = []
    query = "action=continue_pick&id=C1&media=M&programme=2026-10-28T20%3A00%3A00Z~2026-10-28T21%3A00%3A00Z~ct~%3F~kodi"
    query += "&mark=" + mark["id"] + "&at=985"

    def pick(choice, handle="-1"):
        monkeypatch.setattr(xbmcgui.Dialog, "contextmenu", lambda self, options: menus.append(options) or choice)
        ran.clear()
        plugin.Plugin(["plugin://plugin.video.simplego/", handle, "?" + query]).run()

    fail = False
    pick(0)  # resume: there, without asking again
    assert len(menus[0]) == 3 and "0:16:25" in menus[0][0]
    assert ran[0].startswith("PlayMedia(") and "~continue" in ran[0].replace("%7E", "~")
    pick(1)  # from the beginning
    assert "~start" in ran[0].replace("%7E", "~")
    pick(2)  # reset: the web's own delete, then the list again, the row kept greyed out
    assert calls == [("delete", [mark["id"]])] and ran == ["Container.Refresh"]
    assert continuelist.rows([]) == [(dict(mark, title="Film", time_seconds=985, bookmark_type="Catchup"), "removed")]
    fail = True
    calls.clear()
    pick(2)  # the delete refused: the position saved at the start, which the list leaves out
    assert calls == [("delete", [mark["id"]]), ("set", mark["id"], "1", 0, 3600)]
    # A greyed row (nothing to resume): from its beginning at once, no question.
    menus.clear()
    ran.clear()
    plugin.Plugin(["plugin://plugin.video.simplego/", "-1", "?" + query.split("&mark=")[0] + "&start=1"]).run()
    assert menus == [] and len(ran) == 1 and "~start" in ran[0].replace("%7E", "~")
    # Kodi's own "Resume" (context menu, info page) waits for the stream: played at once, its answer kept.
    monkeypatch.setattr(quickplay, "run", lambda argv, started: asked.append(argv) or True)
    menus.clear()
    plugin.Plugin(["plugin://plugin.video.simplego/", "3", "?" + query, "resume:true"]).run()
    assert menus == [] and "action=play" in asked[0][2] and "~resume" in asked[0][2].replace("%7E", "~")


def test_a_greyed_row_can_be_removed_for_good_from_its_context_menu(kodi, monkeypatch, tmp_path):
    import xbmcgui
    import xbmcplugin

    from resources.lib import plugin
    from resources.lib.data import infopages

    continuelist = continue_at(monkeypatch, tmp_path)
    mark = {"id": "1_2026-10-28T20:00:00Z_2026-10-28T21:00:00Z", "title": "Film", "program_id": "F-1", "runtime_seconds": 3600}
    continuelist.rows([dict(mark, time_seconds=600)])  # listed once; gone from the account since: greyed
    account, deleted, ran, menus = [], [], [], []

    class Client:
        def bookmarks(self, details=False):
            return list(account)

        def delete_bookmarks(self, bookmarks):
            deleted.extend(b["id"] for b in bookmarks)

        def airings(self, item_id, kind="series"):
            return [], []

    monkeypatch.setattr(clientfactory, "make_client", Client)
    monkeypatch.setattr(infopages, "pages_for", lambda client, keys, out_dir, full=True: {})
    monkeypatch.setattr(channellist, "by_station", lambda client: {"1": {"id": "C1", "media_id": "M", "name": "M1"}})
    monkeypatch.setattr(xbmcgui.ListItem, "addContextMenuItems", lambda self, items: menus.append(items), raising=False)
    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: None, raising=False)
    monkeypatch.setattr(kodi.xbmc, "executebuiltin", lambda command, wait=False: ran.append(command))
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", "?action=continue"]).run()
    ((label, command),) = [item for item in menus[0] if "continue_remove" in item[1]]
    assert label == "Remove from the list" and "mark=" + mark["id"] in command.replace("%3A", ":")
    # The greyed row: kept here only, nothing to delete from the account.
    plugin.Plugin(["plugin://plugin.video.simplego/", "-1", "?action=continue_remove&mark=" + mark["id"]]).run()
    assert deleted == [] and ran == ["Container.Refresh"] and continuelist.rows([]) == []
    # One the account still has (an expired airing's question): its position goes too.
    account.append(mark)
    plugin.Plugin(["plugin://plugin.video.simplego/", "-1", "?action=continue_remove&mark=" + mark["id"]]).run()
    assert deleted == [mark["id"]]
