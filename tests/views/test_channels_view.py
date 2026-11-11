"""Live channels: the rows, their menus, and the channels that do not play."""

from kodiside import CHANNEL
from kodiside import ON_AIR
from kodiside import G
from kodiside import channel_list

from resources.lib import clientfactory
from resources.lib import kodiutil
from resources.lib.util import localtime
from resources.lib.views import listing


def test_a_channel_row_shows_what_comes_next_and_the_programme_on(monkeypatch):
    monkeypatch.setattr(localtime, "local_time", lambda iso, date=True: "21:05")
    p = channel_list()
    channel = {"number": 1, "name": "M1", "logo": "logo.png", "genres": []}
    on = {
        "description": "Film",
        "full_description": "Plot.",
        "genres": [{"name": "Vígjáték"}],
        "ratings": "12+",
        "image": "pic.jpg",
    }
    following = {"start_time": "2026-10-29T20:05:00Z", "end_time": "2026-10-29T20:30:00Z", "description": "Híradó"}
    li = p.channel_item(channel, on, following, False, True)
    tag = li.getVideoInfoTag()
    # What comes next as the row's second line, grey and italic: the wide list's rows with a logo
    # have no right-hand label.
    assert tag["Plot"] == "Plot." and li.label == "Film[CR][I][COLOR grey]Next: 21:05 - 21:05: Híradó[/COLOR][/I]"
    # Its episode too, as the first line's.
    episode = dict(following, season_number=1, episode_number=2, episode_name="Reggel")
    assert p.channel_item(channel, on, episode, False, True).label.endswith(": Híradó%s[/COLOR][/I]" % (G % " | S1E2: Reggel"))
    # The logo in the row and the side panel; no background (it was hard to read over).
    assert li.art["thumb"] == "logo.png" and not {"poster", "fanart"} & set(li.art)
    assert tag["Mpaa"] == "12+" and tag["Genres"] == ["Vígjáték"] and tag["MediaType"] == "video"
    assert tag["Playcount"] == 0  # never ticked as watched (Kodi counts live as played to its end)
    # The programme's own type, but a film is a video (Estuary puts the logo over its poster then),
    # an episode with its series and numbers.
    film = p.channel_item(channel, dict(on, show_type="Movie", release_year=1989), None, False, True)
    assert film.getVideoInfoTag()["MediaType"] == "video" and film.getVideoInfoTag()["Year"] == 1989
    episode = dict(on, genres=[{"name": "Sorozatok"}], season_number=2, episode_number="5")
    tag = p.channel_item(channel, episode, None, False, True).getVideoInfoTag()
    assert tag["MediaType"] == "episode" and tag["TvShowTitle"] == "Film" and (tag["Season"], tag["Episode"]) == (2, 5)


# The skin's grey a text is put in (see rows.greyed).


def test_the_channel_playing_is_selected_in_the_skins_colour_not_its_category_colour(kodi):
    """As Kodi TV's channel list: the skin colours a selected row; a category colour would hide that."""
    kodi.SETTINGS["colours"] = True  # the "Category colours" setting (off by default)
    p = channel_list()
    news = dict(CHANNEL, genres=["Hír- és politikai műsorok"])
    other = p.channel_item(news, ON_AIR, None, False, True)
    assert "[COLOR" in other.label and "selected" not in other.__dict__
    following = {"start_time": "2026-10-30T20:45:00Z", "end_time": "2026-10-30T21:00:00Z", "description": "Híradó"}
    playing = p.channel_item(news, ON_AIR, following, False, True, playing=True)
    assert playing.selected is True and not playing.label.startswith("[COLOR")
    # The next programme grey and italic there too, as on every row.
    assert playing.label.split("[CR]")[1].startswith("[I][COLOR grey]Next: ")


def test_a_channel_row_fills_the_side_panel_and_the_info_page():
    p = channel_list()
    li = p.channel_item(CHANNEL, ON_AIR, None, False, True)
    tag = li.getVideoInfoTag()
    # The logo in the row and the side panel (its thumb, the larger one); the 2:3 poster on the info page only.
    assert li.art["icon"] == li.art["thumb"] == "logo.png" and "poster" not in li.art
    big = p.channel_item(dict(CHANNEL, logo="https://x/station/1008/4x3/logomedium.png"), ON_AIR, None, False, True)
    assert big.art["thumb"] == "https://x/station/1008/4x3/logolarge.png" and big.art["icon"].endswith("/logomedium.png")
    # Without a programme, the panel shows the logo.
    bare = p.channel_item(dict(CHANNEL, logo="https://x/station/1008/4x3/logomedium.png"), {}, None, False, True)
    assert bare.art["thumb"].endswith("/logolarge.png") and "tvshow.poster" not in bare.art
    assert li.art["tvshow.poster"].endswith("/program/ab-1/2x3/keyartxlarge.jpg")
    assert tag["Title"] == "Első rész" and tag["Studios"] == ["M1"] and tag["Duration"] == 45 * 60
    # Its stream's length too: else Kodi shows the one it kept from playing the channel (its live window).
    assert tag["VideoStream"] == {"duration": 45 * 60}
    assert tag["Tags"] == ["Audio description", "Sign language"]
    # Not the provider's series, but with episode details: an episode on the info page all the same.
    numbered = dict(ON_AIR, season_number=1, episode_number=10, genres=[{"name": "Rajzfilm"}])
    cartoon = p.channel_item(CHANNEL, numbered, None, False, True).getVideoInfoTag()
    assert cartoon["MediaType"] == "episode" and cartoon["TvShowTitle"] == "Sorozat"
    assert (cartoon["Season"], cartoon["Episode"]) == (1, 10)
    plain = dict(ON_AIR, episode_name="", genres=[])
    assert p.channel_item(CHANNEL, plain, None, True, 0).getVideoInfoTag()["MediaType"] == "video"
    radio = dict(CHANNEL, radio=True)
    assert "MediaType" not in p.channel_item(radio, plain, None, True, 0).getVideoInfoTag()


def test_a_channel_row_names_the_programme_with_its_start_and_episode(kodi, monkeypatch):
    p = channel_list()
    monkeypatch.setattr(localtime, "local_time", lambda iso, date=True: "21:00")
    # The channel is not named: it is the side panel's logo and the info page's studio.
    # The episode grey, as on every surface.
    assert p.channel_item(CHANNEL, ON_AIR, None, True, 0).label == "21:00 Sorozat" + G % " | Első rész"
    numbered = dict(ON_AIR, season_number=1, episode_number=10)
    assert p.channel_item(CHANNEL, numbered, None, True, 0).label == "21:00 Sorozat" + G % " | S1E10: Első rész"
    plain = dict(ON_AIR, episode_name="")
    assert p.channel_item(CHANNEL, plain, None, True, 0).label == "21:00 Sorozat"
    assert p.channel_item(CHANNEL, {}, None, True, 0).label == "M1"  # nothing known on air
    kodi.SETTINGS["colours"] = True  # the "Category colours" setting (off by default)
    p = channel_list()
    coloured = p.channel_item(dict(CHANNEL, genres=["Sport"]), plain, None, True, 0).label
    assert coloured.startswith("[COLOR ") and coloured.endswith("]21:00 Sorozat[/COLOR]")  # in its category's colour


def test_a_channel_rows_context_menu_starts_with_play_from_beginning(monkeypatch):
    import xbmcgui

    p = channel_list()
    menus = []
    monkeypatch.setattr(xbmcgui.ListItem, "addContextMenuItems", lambda self, items: menus.append(items), raising=False)
    monkeypatch.setattr(kodiutil, "untrusted_widevine", lambda: False)
    channel = dict(CHANNEL, station_id=None)
    view = {"channels": [channel], "now": {None: ON_AIR}, "subscribed": None, "favourites": None, "ordered": False}
    monkeypatch.setattr(listing, "list_view", lambda call, scope=None: view)
    p.do_channels()
    # In Kodi's own words, the programme on air from its beginning.
    assert menus[0][0][0] == "Play from beginning" and "programme=" in menus[0][0][1]


def test_the_channel_list_has_the_cast_and_colours_the_settings_ask_for(kodi, monkeypatch):
    import xbmcplugin

    from resources.lib.data import infopages

    added = []
    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append(li), raising=False)
    monkeypatch.setattr(localtime, "local_time", lambda iso, date=True: "21:00")
    asked = []

    def pages_for(client, keys, out_dir, full=True):
        asked.append(list(keys))
        return {("program", "F1"): {"type": "movie", "actor": ["Bud Spencer"], "director": ["Corbucci"]}}

    monkeypatch.setattr(infopages, "pages_for", pages_for)
    times = {"start_time": "2026-10-30T20:00:00Z", "end_time": "2026-10-30T21:00:00Z"}
    film = dict(times, program_id="F1", show_type="Movie", description="Film")
    news = dict(times, program_id="N1", description="Híradó")
    channels = [
        {"id": "C1", "media_id": "M", "station_id": "1", "number": 1, "name": "Film+", "logo": "", "genres": ["Sport"]},
        {"id": "C2", "media_id": "M", "station_id": "2", "number": 2, "name": "M1", "logo": "", "genres": []},
    ]
    view = {"channels": channels, "now": {"1": film, "2": news}, "subscribed": None, "favourites": None, "ordered": False}

    def listed(**settings):
        kodi.SETTINGS.clear()
        kodi.SETTINGS.update(settings)
        added.clear()
        p = channel_list()
        monkeypatch.setattr(listing, "list_view", lambda call, scope=None: view)
        p.do_channels()
        return added

    # By default no cast (no info page asked for) and no colours.
    rows = listed()
    assert asked == [] and "Cast" not in rows[0].getVideoInfoTag() and rows[0].label == "21:00 Film"
    # Films' cast only: only the film's page is asked for.
    rows = listed(info_movie=True)
    assert asked == [[("program", "F1")]]
    assert rows[0].getVideoInfoTag()["Cast"] == ["Bud Spencer"] and rows[0].getVideoInfoTag()["Directors"] == ["Corbucci"]
    assert "Cast" not in rows[1].getVideoInfoTag()
    # Colours on: in the channel's category colour.
    rows = listed(colours=True)
    assert rows[0].label.startswith("[COLOR ") and rows[0].label.endswith("]21:00 Film[/COLOR]")


def test_live_channels_list_every_channel_at_once_one_not_playing_by_its_name_and_why(kodi, monkeypatch):
    """No folders any more; sortable by own order, name and number in Kodi's side menu; no channel order items here."""
    import xbmcgui
    import xbmcplugin

    p = channel_list()
    added, menus, sorts = [], [], []
    monkeypatch.setattr(
        xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append((url, li)), raising=False
    )
    monkeypatch.setattr(xbmcplugin, "addSortMethod", lambda handle, method, labelMask="": sorts.append(labelMask), raising=False)
    monkeypatch.setattr(xbmcgui.ListItem, "addContextMenuItems", lambda self, items: menus.append(items), raising=False)
    monkeypatch.setattr(kodiutil, "untrusted_widevine", lambda: False)
    off = dict(CHANNEL, id="C2", number=2, name="M2", station_id="S2")
    outside = dict(CHANNEL, id="C3", number=3, name="M3", station_id="S3")
    view = {
        "channels": [dict(CHANNEL, station_id="S1"), off, outside],
        "now": {"S1": ON_AIR},
        "subscribed": ["C1", "C2"],
        "favourites": ["C2"],
        "deactivated": ["C2"],
        "ordered": True,
    }
    monkeypatch.setattr(listing, "list_view", lambda call, scope=None: view)
    p.do_channels()
    (url, live), (off_url, deactivated), (out_url, unsubscribed) = added
    assert "action=play" in url and live.properties["IsPlayable"] == "true"
    assert "action=deactivated" in off_url and deactivated.properties["IsPlayable"] == "false"
    # Its name and why, no programme; the logo kept. Outside the subscription, in Kodi's words: a click
    # says which package it is in.
    beside = "[COLOR grey]%s[/COLOR]  [I][COLOR grey]%s[/COLOR][/I]"  # the name grey, why beside it in italics
    assert deactivated.label == beside % ("M2", "Deactivated") and deactivated.art["icon"] == "logo.png"
    assert unsubscribed.label == beside % ("M3", "Not available") and "action=not_subscribed" in out_url
    tag = deactivated.getVideoInfoTag()
    assert tag["Studios"] == ["M2"] and tag["TrackNumber"] == 2 and tag["ProductionCode"] == "0001"
    assert "Title" not in tag  # untitled: Kodi offers no Play of its own for it
    # Kodi's own favourites item hidden on every row: the account's favourites carry its words.
    assert all(li.properties["hide_add_remove_favourite"] == "true" for _, li in added)
    # The greyed ones' menu: the favourites only; none offers the channel order (My channels' now).
    assert [label for label, _ in menus[1]] == ["Remove from favourites"]
    assert [label for label, _ in menus[2]] == ["Add to favourites"]
    assert not any("action=move" in action or "action=reset_order" in action for menu in menus for _, action in menu)
    assert sorts == ["%L", "%L", "%L"]  # own order (production code), by name (studio), by number (track)
    # A click on the deactivated one says why it does not play.
    p.do_deactivated()
    assert [m for m, kind in kodi.LOG if kind == "ok"] == [
        "This channel is deactivated. You can activate it again under My channels."
    ]


def test_a_channel_outside_the_subscription_says_its_cheapest_package(kodi, monkeypatch):
    from resources.lib import plugin
    from resources.lib.data import onair

    monkeypatch.setattr(onair, "on_air", lambda client, station, when: ({"program_id": "P-%s" % station}, None))
    asked = []

    class Client:
        def offers(self, program_id):
            asked.append(program_id)
            offer = {"package_name": "Telekom TV M csomag", "price": 6990, "currency": "HUF"}
            return [offer, dict(offer, package_name="Telekom TV L csomag", price=9990.0)]

    monkeypatch.setattr(clientfactory, "make_client", Client)
    plugin.run(["plugin://plugin.video.simplego/", "-1", "?action=not_subscribed&station=1010"])
    assert asked == ["P-1010"]
    assert [m for m, kind in kodi.LOG if kind == "ok"] == [
        "Channel not in your subscription. Available in: Telekom TV M csomag (6990 Ft/month)"
    ]
    # Nothing known (no programme, no offer): the service's own refusal, in its words.
    monkeypatch.setattr(onair, "on_air", lambda client, station, when: (None, None))
    plugin.run(["plugin://plugin.video.simplego/", "-1", "?action=not_subscribed&station=1010"])
    assert [m for m, kind in kodi.LOG if kind == "ok"][-1] == "A subscription is needed to watch this content!"


def test_a_channel_list_asked_for_while_one_is_being_made_ends_as_failed(kodi, monkeypatch):
    import time

    import xbmcplugin

    from resources.lib.views import channels

    ended, made = [], []
    monkeypatch.setattr(xbmcplugin, "endOfDirectory", lambda handle, succeeded=True, **kw: ended.append(succeeded), raising=False)
    view = channel_list()
    monkeypatch.setattr(view, "_list_channels", lambda: made.append(kodi.PROPERTIES.get(channels.LISTING)))
    view.do_channels()
    assert made and made[0] and channels.LISTING not in kodi.PROPERTIES  # marked while made, then cleared
    # Another list being made right now (Kodi's own reload): this one ends at once, failed.
    kodi.PROPERTIES[channels.LISTING] = str(time.time())
    view.do_channels()
    assert ended == [False] and len(made) == 1
    # A mark a crashed listing left behind long ago: listed as usual.
    kodi.PROPERTIES[channels.LISTING] = str(time.time() - channels.LISTING_STALE - 1)
    view.do_channels()
    assert len(made) == 2


def test_while_something_plays_the_list_selects_the_channel_last_played(kodi, monkeypatch):
    import xbmc
    import xbmcplugin

    from resources.lib.service import quickplay

    p = channel_list()
    added = []
    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append(li), raising=False)
    other = dict(CHANNEL, id="C2", number=2, name="M2", station_id="S2")
    view = {"channels": [dict(CHANNEL, station_id="S1"), other], "now": {}, "subscribed": None, "favourites": None}
    monkeypatch.setattr(listing, "list_view", lambda call, scope=None: view)
    monkeypatch.setattr(xbmc.Player, "isPlaying", lambda self: True)
    kodiutil.home().setProperty(quickplay.PLAYING, "C2")
    try:
        p.do_channels()
    finally:
        kodiutil.home().clearProperty(quickplay.PLAYING)
    assert [li.__dict__.get("selected", False) for li in added] == [False, True]
