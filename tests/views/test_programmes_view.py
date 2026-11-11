"""Favourite programmes: the list, the seasons and the airings' picker."""

import pytest
from kodiside import COMING
from kodiside import NEWER
from kodiside import OLD
from kodiside import G

from resources.lib import clientfactory
from resources.lib import kodiutil
from resources.lib.data import channellist
from resources.lib.util import localtime
from resources.lib.views import listing


def test_favourite_programme_rows_have_plots_types_posters_and_film_years(monkeypatch):
    import xbmcplugin

    from resources.lib import plugin
    from resources.lib.data import infopages

    added = []
    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append(li), raising=False)
    monkeypatch.setattr(
        infopages, "pages_for", lambda client, keys, out_dir, full=True: {key: {"plot": "Plot of %s" % key[1]} for key in keys}
    )

    class Client:
        def watchlist(self):
            series = {"id": "S1", "name": "UFC", "show_type": "Series", "description": ""}
            return [series, {"id": "P1", "name": "Film", "release_year": 2017}]

        def airings(self, item_id, kind):
            airing = {"program_id": "AB-1", "name": "UFC", "start_utc": "2026-10-28T20:00:00Z", "station_id": "1"}
            return [dict(airing, end_utc="2026-10-28T21:00:00Z"), dict(airing, end_utc="2026-10-28T21:00:00Z")], []

    monkeypatch.setattr(clientfactory, "make_client", Client)
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", "?action=watchlist"]).run()
    tags = [li.getVideoInfoTag() for li in added]
    assert [(t["Plot"], t["MediaType"]) for t in tags] == [("Plot of S1", "tvshow"), ("Plot of P1", "movie")]
    # The series' own poster for a series, the programme's for a single one.
    assert added[0].art["poster"].endswith("/series/s1/2x3/keyartxlarge.jpg")
    assert added[1].art["poster"].endswith("/program/p1/2x3/keyartxlarge.jpg")
    # In the row, Kodi's icon by type; no thumb, which the row would show instead.
    assert [li.art["icon"] for li in added] == ["DefaultTVShows.png", "DefaultMovies.png"]
    assert not any("thumb" in li.art for li in added)
    assert [li.label for li in added] == ["UFC", "Film (2017)"]  # a film's year after its title
    # Kodi's own favourites item off: ours (removing it) in its words.
    assert all(li.properties["hide_add_remove_favourite"] == "true" for li in added)
    # A click opens a series' seasons or picks a programme's airing: never a playable item.
    assert all(li.properties.get("IsPlayable") != "true" for li in added)


@pytest.fixture
def picker(kodi, monkeypatch):
    """The airing picker of a favourite: its airings, what it showed and played; pick(query) runs it."""
    import types

    import xbmcgui
    import xbmcplugin

    from resources.lib import plugin

    state = types.SimpleNamespace(back=[], coming=[], choice=0, shown=[], headings=[], played=[])
    monkeypatch.setattr(kodi.xbmc, "executebuiltin", lambda command, wait=False: state.played.append(command.split("?", 1)[1]))
    resolved = []
    monkeypatch.setattr(xbmcplugin, "setResolvedUrl", lambda h, ok, li: resolved.append(ok), raising=False)
    channel = {"id": "C1", "media_id": "M", "name": "RTL", "logo": "l.png"}
    monkeypatch.setattr(channellist, "by_station", lambda client: {"1": channel})

    class Client:
        def airings(self, item_id, kind):
            return state.back, state.coming

    monkeypatch.setattr(clientfactory, "make_client", Client)

    def select(self, heading, options, preselect=-1, useDetails=False):
        state.headings.append(heading)
        state.shown.append(([o.label for o in options], preselect, [o.label2 for o in options]))
        return state.choice

    monkeypatch.setattr(xbmcgui.Dialog, "select", select)

    def pick(query="action=pick&id=P1&kind=program", handle="-1"):  # a click: no handle
        plugin.Plugin(["plugin://plugin.video.simplego/", handle, "?" + query]).run()
        # Never a resolve: the favourite's row is an action, not a playable item (no "Playback failed").
        assert resolved == []

    state.pick = pick
    return state


def test_the_picker_lists_each_airing_once_oldest_first_and_plays_the_one_picked_where_left_off(picker):
    elsewhere = dict(OLD, station_id="9")  # not a channel of the subscription
    picker.back, picker.coming = [NEWER, OLD, dict(OLD), elsewhere], [COMING]
    picker.pick()
    # The coming one grey; the latest that can play preselected.
    ((labels, preselect, below),) = picker.shown
    # The channel, below it Kodi's short date and the start only (the stub's "%Y-%m-%d" and "%H:%M").
    # Those that play in the skin's own colour; the coming one grey.
    assert labels == ["RTL", "RTL", "[COLOR grey]RTL[/COLOR]"]
    assert below[0].startswith("2026-10-27 ") and below[2].startswith("2099-01-01 ")
    assert len(below[0]) == len("2026-10-27 22:30")
    assert preselect == 1
    # Played without asking where to start again: the picker was the question.
    (played,) = picker.played
    assert "programme=2026-10-27T21" in played.replace("%3A", ":") and played.endswith("~continue)")


def test_a_coming_airing_picked_plays_nothing_and_says_so(picker, kodi):
    picker.back, picker.coming, picker.choice = [NEWER, OLD], [COMING], 2
    picker.pick()
    assert picker.played == [] and ("Not on yet", "notification") in kodi.LOG


def test_the_only_airing_that_can_play_plays_without_a_picker(picker):
    picker.back = [NEWER]
    picker.pick()
    assert picker.shown == [] and len(picker.played) == 1


def test_a_series_airings_in_the_picker_say_their_episode(picker, monkeypatch):
    from resources.lib.data import infopages

    monkeypatch.setattr(infopages, "episode_numbers", lambda client, ids, out_dir: {"E1": (1, 3)})
    picker.back = [dict(OLD, program_id="E1"), NEWER]
    picker.pick("action=pick&id=S1&kind=series")
    assert picker.shown[0][2][0].endswith(G % " | S1E3")


def test_only_coming_airings_are_shown_to_read_and_none_plays(picker):
    picker.coming = [COMING]
    picker.pick()
    assert picker.headings == ["Further airings"] and picker.played == [] and len(picker.shown) == 1


def test_a_further_airing_picked_says_it_is_not_on_yet(picker, kodi):
    picker.coming, picker.choice = [COMING], 0
    picker.pick()
    assert ("Not on yet", "notification") in kodi.LOG
    kodi.LOG.clear()
    picker.choice = -1  # closed with Back: nothing said
    picker.pick()
    assert ("Not on yet", "notification") not in kodi.LOG


def test_without_airings_the_next_one_the_favourites_list_knows_is_shown(picker):
    # Some series have no airings of their own: shown without a channel, only to read.
    picker.pick("action=pick&id=S2&kind=series&start=2099-11-02T00:05:00Z&end=2099-11-02T01:00:00Z")
    assert picker.headings == ["Further airings"] and picker.shown[0][0][0].startswith("[COLOR grey]2099-11-02 ")


def test_without_any_airing_a_notification_says_so(picker, kodi):
    picker.pick()
    assert picker.shown == [] and ("No airing known", "notification") in kodi.LOG


def test_a_favourite_series_lists_its_seasons_and_a_season_its_airings(kodi, monkeypatch):
    import xbmcgui
    import xbmcplugin

    from resources.lib import plugin

    added, shown, played = [], [], []
    monkeypatch.setattr(
        xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append((url, li, isFolder)), raising=False
    )
    monkeypatch.setattr(kodi.xbmc, "executebuiltin", lambda command, wait=False: played.append(command), raising=False)
    labels = lambda self, heading, options, **kw: shown.append([(o.label, o.label2) for o in options]) or 0  # noqa: E731
    monkeypatch.setattr(xbmcgui.Dialog, "select", labels)
    channel = {"id": "C1", "media_id": "M", "name": "Duna", "logo": ""}
    monkeypatch.setattr(channellist, "by_station", lambda client: {"1005": channel})
    airing = {"station_id": "1005", "program_id": "E36", "entitlements": ["ct"]}
    seasons = [{"id": "S_9", "number": 9, "display_name": "Évad 9", "episodes_count": 10}]

    class Client:
        def details(self, kind, item_id):
            return {"name": "Bor, mámor, szerelem", "seasons": seasons}

        def season(self, series_id, season_id, number):
            assert (series_id, season_id, number) == ("S1", "S_9", 9)
            back = dict(airing, start_utc="2026-10-28T18:50:00Z", end_utc="2026-10-28T19:40:00Z")
            coming = dict(airing, program_id="E37", start_utc="2099-11-02T18:50:00Z", end_utc="2099-11-02T19:40:00Z")
            return [
                {"id": "E36", "number": "36", "name": "A szüret", "actions": {"catchup_schedules": [back], "schedules": []}},
                {"id": "E37", "number": "37", "actions": {"catchup_schedules": [], "schedules": [coming]}},
            ]

        def airings(self, item_id, kind):
            return [], []

    monkeypatch.setattr(clientfactory, "make_client", Client)
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", "?action=seasons&id=S1"]).run()
    ((url, li, folder),) = added
    tag = li.getVideoInfoTag()
    # Its episodes beside its name, grey in brackets, by Kodi's playlist icon.
    assert li.label == "Évad 9 [COLOR grey](10 episodes)[/COLOR]" and li.art["icon"] == "DefaultVideoPlaylists.png"
    assert tag["MediaType"] == "season" and tag["Season"] == 9 and not folder
    assert "action=pick" in url and "season=S_9" in url
    # A click (no handle): the season's airings, each with its episode, the one watched back played.
    plugin.Plugin(["plugin://plugin.video.simplego/", "-1", "?" + url.split("?", 1)[1]]).run()
    # The channel above, the time and the episode (its title where the season has it) below; a coming one grey.
    assert [label for label, _ in shown[0]] == ["Duna", "[COLOR grey]Duna[/COLOR]"]
    assert [line2.split(" | ")[-1] for _, line2 in shown[0]] == ["S9E36: A szüret[/COLOR]", "S9E37[/COLOR]"]
    assert len(played) == 1 and "2026-10-28T18" in played[0].replace("%3A", ":")
    # A series without seasons: its own airings, picked from at once (none here: a notification).
    seasons.clear()
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", "?action=seasons&id=S1"]).run()
    assert ("No airing known", "notification") in kodi.LOG


def test_a_picker_row_says_now_instead_of_the_time_of_an_airing_on_air(kodi, monkeypatch):
    from resources.lib.views import programmes

    monkeypatch.setattr(localtime, "local_time", lambda iso, date=True: "2026.11.01. 21:00")
    channel = {"name": "Duna", "logo": "logo.png"}
    airing = {"start_utc": "2026-11-01T20:00:00Z", "episode_name": "A szüret"}
    on_now = programmes.pick_row(airing, channel, True, numbers=(9, 36))
    # In the skin's own colour where it plays, the episode grey.
    assert (on_now.label, on_now.label2) == ("Duna", "Now" + G % " | S9E36: A szüret")
    later = programmes.pick_row(dict(airing, episode_name=""), channel, False, can_play=False)
    assert (later.label, later.label2) == ("[COLOR grey]Duna[/COLOR]", "2026.11.01. 21:00")


def test_an_airing_on_a_channels_hd_and_sd_versions_is_listed_once_the_hd_one(kodi):
    from resources.lib.views import programmes

    channels = {"1": {"id": "C1", "name": "Viasat 3"}, "2": {"id": "C2", "name": "Viasat 3 HD"}}
    airing = {"program_id": "P1", "start_utc": "2026-10-27T22:45:00Z", "end_utc": "2026-10-27T23:50:00Z"}
    back = [dict(airing, station_id="1"), dict(airing, station_id="2"), dict(airing, station_id="1")]
    rows = programmes.pick_rows(back, [], channels, "2026-10-30T20:00:00Z")
    assert [row[1]["name"] for row in rows] == ["Viasat 3 HD"]


def test_a_favourites_click_follows_kodis_default_select_action(kodi, picker, monkeypatch):
    """Kodi applies "Default select action" to playable rows only: a favourite's click does it itself."""

    opened = []
    picker.back = [OLD]
    monkeypatch.setattr(kodi.xbmc, "executebuiltin", lambda command, wait=False: opened.append(command))
    for action, expected in ((3, ["Action(Info)"]), (0, ["Action(ContextMenu)"])):
        monkeypatch.setattr(kodiutil, "kodi_setting", lambda setting, default=None, value=action: value)
        picker.pick()
        assert opened == expected and picker.shown == []
        opened.clear()
    # "Play" (Kodi's default) picks.
    monkeypatch.setattr(kodiutil, "kodi_setting", lambda setting, default=None: listing.SELECT_PLAY)
    picker.pick()
    assert len(opened) == 1 and "action=play" in opened[0]


def test_kodis_own_play_of_a_favourite_plays_at_once_or_says_why_not(kodi, picker, monkeypatch):
    """Kodi's "Play" (context menu, info page) waits for a stream: no picker, which kept it waiting."""
    import xbmcgui
    import xbmcplugin

    from resources.lib.service import quickplay

    asked, resolved, told = [], [], []
    monkeypatch.setattr(quickplay, "run", lambda argv, started: asked.append(argv) or True)
    monkeypatch.setattr(xbmcplugin, "setResolvedUrl", lambda handle, ok, li: resolved.append(ok), raising=False)
    monkeypatch.setattr(xbmcgui.Dialog, "notification", lambda self, *a, **kw: told.append(a[1]), raising=False)
    picker.back, picker.coming = [OLD, NEWER], [COMING]
    picker.pick(handle="1")
    # The one the picker would preselect (the latest that can play), resumed without asking, through the service.
    ((base, handle, query),) = asked
    assert handle == "1" and "action=play" in query and picker.shown == [] and not told
    # Nothing to play: why at once (the next airing), and no stream.
    picker.back = []
    asked.clear()
    picker.pick(handle="1")
    assert asked == [] and resolved == [False] and told[0].startswith("Further airings: 2099-01-01 ")


def test_a_favourite_change_is_said_done_only_once_the_list_says_so(kodi):
    from kodiside import call

    from resources.lib.views import programmes

    class Account:
        def __init__(self, keeps):
            self.keeps, self.listed = keeps, []

        def set_watchlist(self, item_id, on, kind="series"):
            if self.keeps and on:
                self.listed.append({"id": item_id})

        def watchlist(self):
            return self.listed

    programmes.ProgrammeViews(call("?action=watch&id=P1&kind=program&on=1", "-1", client=Account(keeps=True))).do_watch()
    assert ("Added to favourite programmes", "notification") in kodi.LOG
    # Taken without a word but left out of the list (a film with no airing left): said so.
    kodi.LOG.clear()
    programmes.ProgrammeViews(call("?action=watch&id=P2&kind=program&on=1", "-1", client=Account(keeps=False))).do_watch()
    assert ("The provider did not add it to the favourite programmes.", "notification") in kodi.LOG
    assert ("Container.Refresh", "builtin") in kodi.LOG
