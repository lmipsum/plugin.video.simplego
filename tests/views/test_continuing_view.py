"""Continue watching: the rows and a row's click."""

from kodiside import G
from kodiside import continue_at

from resources.lib import clientfactory
from resources.lib import kodiutil
from resources.lib.data import channellist
from resources.lib.util import localtime
from resources.lib.views import listing


def test_continue_watching_rows_show_the_programme_its_episode_poster_and_length(kodi, monkeypatch):
    import xbmcplugin

    from resources.lib import plugin
    from resources.lib.data import infopages

    continue_at(monkeypatch)
    monkeypatch.setattr(localtime, "local_date", lambda stamp: "2026.11.04.")

    added = []
    urls, sorts = [], []
    add = lambda handle, url, li, isFolder=False: added.append(li) or urls.append(url)  # noqa: E731
    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", add, raising=False)
    monkeypatch.setattr(xbmcplugin, "addSortMethod", lambda handle, method, **masks: sorts.append(masks), raising=False)
    pages = {("program", "F-1"): {"type": "movie", "year": 2017}, ("program", "AB-1"): {"type": "series", "year": 2010}}
    kept = lambda client, keys, out_dir, full=True: {k: pages[k] for k in keys if k in pages}  # noqa: E731
    monkeypatch.setattr(infopages, "pages_for", kept)
    channel = {"id": "C1", "media_id": "M", "name": "Channel One", "logo": "logo.png"}
    monkeypatch.setattr(channellist, "by_station", lambda client: {"1": channel})

    class Client:
        def bookmarks(self, details=False):
            mark = {"id": "1_2026-10-28T20:00:00Z_2026-10-28T21:00:00Z", "title": "Sorozat", "program_id": "AB-1"}
            film = dict(mark, id="1_2026-10-28T21:00:00Z_2026-10-28T23:00:00Z", title="Tűnj el!", program_id="F-1")
            film.update(time_seconds=600, runtime_seconds=7200)
            soon = dict(film, id="1_2026-10-26T20:00:00Z_2026-10-26T22:30:00Z", title="Hamarosan", program_id="S-1")
            return [dict(mark, season_number=2, episode_number=5, time_seconds=600, runtime_seconds=3600), film, soon]

        def airings(self, item_id, kind="series"):
            # The films' airings still on catch-up, the episode's not any more.
            if item_id == "F-1":
                return [{"station_id": "1", "start_utc": "2026-10-28T21:00:00Z"}], []
            if item_id == "S-1":
                return [{"station_id": "1", "start_utc": "2026-10-26T20:00:00Z"}], []
            return [{"station_id": "1", "start_utc": "2026-10-21T20:00:00Z"}], []

    monkeypatch.setattr(clientfactory, "make_client", Client)
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", "?action=continue"]).run()
    # The soonest to leave catch-up first; the expired episode at the bottom, though the account lists it first.
    soon, film, episode = added
    assert soon.label == "Hamarosan" and film.label == "Tűnj el! (2017)"  # a film's year after its title (its info page)
    # On the right (the production code, see rows): how long it is expected to stay; for the expired one, that.
    assert sorts == [{"labelMask": "%L", "label2Mask": "%P"}]
    assert soon.getVideoInfoTag()["ProductionCode"] == "11 hours left"  # 22:30Z + 72 h, at 12:00Z three days on: 10.5 h
    assert film.getVideoInfoTag()["ProductionCode"] == "2 days left"  # 23:00Z + 72 h, at 12:00Z the next day: 59 h
    tag = episode.getVideoInfoTag()
    assert tag["ProductionCode"] == "Expired" and episode.label == G % ("Sorozat" + G % " | S2E5")
    # Expired: no resume, no tick; a click says so (see the next test) without playing.
    assert "ResumePoint" not in tag and tag["Playcount"] == 0 and "expired=1" in urls[2] and "start=1" not in urls[2]
    assert tag["MediaType"] == "episode" and (tag["Season"], tag["Episode"]) == (2, 5)
    assert tag["Studios"] == ["Channel One"] and tag["Duration"] == 3600 and tag["VideoStream"] == {"duration": 3600}
    assert episode.art["poster"].endswith("/program/ab-1/2x3/keyartxlarge.jpg")  # the side panel: the programme's
    # Whether each is still on catch-up by its programme's airings: logged too.
    logged = [m for m, _ in kodi.LOG if m.startswith("[plugin.video.simplego] catch-up of")]
    assert len(logged) == 3 and "(Sorozat, active): gone" in logged[1] and "(Tűnj el!, active): on" in logged[2]
    # Kodi's own favourites item off, ours in its words.
    assert all(li.properties["hide_add_remove_favourite"] == "true" for li in added)
    assert "icon" not in episode.art
    assert film.getVideoInfoTag()["MediaType"] == "movie" and film.getVideoInfoTag()["Year"] == 2017
    # The 16:9 picture as background; no thumb, else Estuary's info page puts the poster over itself.
    for li in added:
        assert "thumb" not in li.art and li.art["fanart"].endswith("/16x9/keyartxlarge.jpg")
        assert li.properties["IsPlayable"] == "false"  # an action opening the picker (see the next test)
    for li in (soon, film):  # the resume point kept for the row's icon
        assert li.getVideoInfoTag()["ResumePoint"]


def test_greyed_rows_are_ticked_while_on_catch_up_and_not_once_expired(kodi, monkeypatch):
    """Gone from the account's list: ticked while on catch-up, whether watched to its end or reset; expired, not."""
    import xbmcplugin

    from resources.lib import plugin
    from resources.lib.data import infopages

    continuelist = continue_at(monkeypatch)
    added = []
    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append(li), raising=False)
    monkeypatch.setattr(infopages, "pages_for", lambda client, keys, out_dir, full=True: {})
    monkeypatch.setattr(channellist, "by_station", lambda client: {"1": {"id": "C1", "media_id": "M", "name": "Channel One"}})

    def mark(n, title):
        start, end = "2026-10-2%dT20:00:00Z" % n, "2026-10-2%dT21:00:00Z" % n
        return {"id": "1_%s_%s" % (start, end), "title": title, "program_id": title, "time_seconds": 600, "runtime_seconds": 3600}

    watched, reset, expired = mark(8, "Watched"), mark(7, "Reset"), mark(6, "Expired")
    continuelist.rows([watched, reset, expired])  # listed once; gone from the account's list since
    continuelist.set_removed(reset)

    class Client:
        def bookmarks(self, details=False):
            return []

        def airings(self, item_id, kind="series"):
            on = {"Watched": "2026-10-28T20:00:00Z", "Reset": "2026-10-27T20:00:00Z"}  # the expired one: none
            return ([{"station_id": "1", "start_utc": on[item_id]}] if item_id in on else []), []

    monkeypatch.setattr(clientfactory, "make_client", Client)
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", "?action=continue"]).run()
    ticks = {li.getVideoInfoTag()["Title"]: li.getVideoInfoTag()["Playcount"] for li in added}
    assert ticks == {"Reset": 1, "Watched": 1, "Expired": 0}
    assert added[-1].getVideoInfoTag()["ProductionCode"] == "Expired"  # at the bottom


def test_a_continue_watching_row_resumes_plays_from_the_beginning_or_resets_its_position(kodi, monkeypatch):
    """A click: Kodi's resume question in its own words, plus resetting the position (deleting it)."""
    import xbmcgui

    from resources.lib import plugin
    from resources.lib.service import quickplay

    continuelist = continue_at(monkeypatch)

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
    pick(2)  # reset: the delete, then the list again, the row kept greyed out
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
    # "noresume": else Kodi asks its own resume question for an address it kept a position for.
    assert menus == [] and len(ran) == 1 and "~start" in ran[0].replace("%7E", "~") and ran[0].endswith(",noresume)")
    # Kodi's own "Resume" (context menu, info page) waits for the stream: played at once, its answer kept.
    monkeypatch.setattr(quickplay, "run", lambda argv, started: asked.append(argv) or True)
    menus.clear()
    plugin.Plugin(["plugin://plugin.video.simplego/", "3", "?" + query, "resume:true"]).run()
    assert menus == [] and "action=play" in asked[0][2] and "~resume" in asked[0][2].replace("%7E", "~")


def test_a_greyed_row_can_be_removed_for_good_from_its_context_menu(kodi, monkeypatch):
    import xbmcgui
    import xbmcplugin

    from resources.lib import plugin
    from resources.lib.data import infopages

    continuelist = continue_at(monkeypatch)
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
    monkeypatch.setattr(channellist, "by_station", lambda client: {"1": {"id": "C1", "media_id": "M", "name": "Channel One"}})
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


def test_an_expired_row_says_so_and_offers_its_removal_without_playing(kodi, monkeypatch):
    from resources.lib import plugin
    from resources.lib.data import watchoffer

    mark_id = "1246_2026-11-12T08:45:00Z_2026-11-12T11:25:00Z"
    asked = []
    monkeypatch.setattr(clientfactory, "make_client", lambda: object())
    offer = lambda client, channel, programme: asked.append(programme) or {"mark": mark_id}  # noqa: E731
    monkeypatch.setattr(watchoffer, "offer_for_play", offer)
    kodi.ANSWERS["yesno"] = True
    query = "action=continue_pick&id=C1&media=M&programme=2026-11-12T08%3A45%3A00Z~2026-11-12T11%3A25%3A00Z~ct~12~kodi&expired=1"
    plugin.Plugin(["plugin://plugin.video.simplego/", "-1", "?" + query]).run()
    ran = [m for m, kind in kodi.LOG if kind == "builtin"]
    assert asked and not any("PlayMedia" in m for m in ran)  # Kodi's own resume question has no chance to come
    assert len(ran) == 1 and "action=continue_remove" in ran[0] and "mark=" in ran[0]
