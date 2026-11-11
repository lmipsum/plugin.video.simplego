"""The plugin's main menu and its calls."""

from kodiside import continue_at

from resources.lib import clientfactory
from resources.lib.data import channellist


def test_the_main_menu_rows_have_kodis_own_icons(kodi, monkeypatch):
    import xbmcplugin

    from resources.lib import plugin

    added = []
    monkeypatch.setattr(xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append(li), raising=False)
    monkeypatch.setattr(clientfactory, "has_login", lambda: True)
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", ""]).run()
    icons = [li.art.get("icon") for li in added]
    # No settings row: Kodi's side menu has the add-on's settings.
    assert len(icons) == 5 and all(icon and icon.startswith("Default") for icon in icons)


def test_the_main_menu_says_the_channel_and_programme_counts_timing_each(kodi, monkeypatch):
    import xbmcplugin

    from resources.lib import plugin

    channellist.set_deactivated(2, True)
    channellist.set_deactivated(9, True)  # no longer subscribed: not counted
    labels = []
    monkeypatch.setattr(
        xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: labels.append(li.label), raising=False
    )
    monkeypatch.setattr(clientfactory, "has_login", lambda: True)

    class Client:
        def subscribed_ids(self):
            return {1, 2, 3}

        def channel_list(self, scope="all"):
            return [{"id": 1}, {"id": 7}]

        def watchlist(self):
            return [{"show_type": "Series"}, {"show_type": "Series"}, {"show_type": "Program"}]

    monkeypatch.setattr(clientfactory, "make_client", Client)
    # No play service running: made here.
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", ""]).run()
    note = "  [I][COLOR grey]%s[/COLOR][/I]"  # beside the row, grey and italic
    assert labels[:4] == [
        "Live channels" + note % "3 subscribed channels",
        "My channels" + note % "Favourite: 2 | Deactivated: 1",
        "Favourite programmes" + note % "TV shows: 2 | Other: 1",  # Kodi's word for series
        # Nothing beside it: when a programme leaves catch-up varies by channel, and no list says (see continuelist).
        "Continue watching",
    ]
    (timed,) = [m for m, level in kodi.LOG if "main menu counts" in m]
    assert "made here" in timed and "first since" in timed
    assert all(part in timed for part in ("subscribed", "favourites", "deactivated", "watchlist"))
    # The second time is said so.
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", ""]).run()
    assert [m for m, _ in kodi.LOG if "main menu counts" in m][-1].endswith("(again)")


def test_the_main_menu_takes_its_counts_from_the_play_service(kodi, monkeypatch):
    import xbmcplugin

    from resources.lib import plugin
    from resources.lib.data import menucounts
    from resources.lib.service import pluginrequests
    from resources.lib.service import quickplay

    continue_at(monkeypatch)

    class Client:
        def sync(self):
            pass

        def subscribed_ids(self):
            return {1, 2}

        def channel_list(self, scope="all"):
            return [{"id": 1}]

        def bookmarks(self, details=False):
            return []

        def watchlist(self):
            return []

    served = pluginrequests.Lists(Client).menu_counts()
    assert {k: served[k] for k in ("subscribed", "favourites", "deactivated")} == {
        "subscribed": 2,
        "favourites": 1,
        "deactivated": 0,
    }
    assert served == dict(menucounts.counts(Client()), timed=served["timed"])
    labels, asked = [], []
    monkeypatch.setattr(
        xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: labels.append(li.label), raising=False
    )
    monkeypatch.setattr(clientfactory, "has_login", lambda: True)
    monkeypatch.setattr(quickplay, "ask", lambda path, timeout, **q: asked.append(path) or served)
    monkeypatch.setattr(clientfactory, "make_client", lambda: (_ for _ in ()).throw(AssertionError("no client here")))
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", ""]).run()
    assert asked == ["/menu"] and labels[0].endswith("[COLOR grey]2 subscribed channels[/COLOR][/I]")
    assert any("main menu counts from the service" in m for m, _ in kodi.LOG)


def test_an_unknown_action_ends_its_listing_quietly(kodi, monkeypatch):
    """An address from an older version (a favourite, a widget) ends its listing as failed, no script error."""
    import xbmcplugin

    from resources.lib import plugin

    ended = []
    monkeypatch.setattr(xbmcplugin, "endOfDirectory", lambda handle, succeeded=True, **kw: ended.append(succeeded), raising=False)
    plugin.Plugin(["plugin://plugin.video.simplego/", "1", "?action=subscribed"]).run()
    assert ended == [False] and any("unknown action: subscribed" in m for m, _ in kodi.LOG)
