"""My channels: the manager and the list changes it makes."""

from kodiside import CHANNEL
from kodiside import call

from resources.lib import clientfactory
from resources.lib import kodiutil
from resources.lib.data import channellist
from resources.lib.views import listing
from resources.lib.views import mychannels


def test_my_channels_manage_every_channel_and_play_none(kodi, monkeypatch, tmp_path):
    """A star for a favourite, "Not subscribed" said, a click opens the same menu as a long press."""
    import xbmcgui
    import xbmcplugin

    from resources.lib import plugin

    monkeypatch.setattr(channellist, "DEACTIVATED", str(tmp_path / "deactivated.json"))
    p = mychannels.MyChannelsViews(call("?action=mychannels"))
    added, menus = [], []
    monkeypatch.setattr(
        xbmcplugin, "addDirectoryItem", lambda handle, url, li, isFolder=False: added.append((url, li)), raising=False
    )
    monkeypatch.setattr(xbmcgui.ListItem, "addContextMenuItems", lambda self, items: menus.append(items), raising=False)
    channels = [
        dict(CHANNEL, id="F", number=1, name="Fav"),
        dict(CHANNEL, id="S", number=2, name="Sub"),
        dict(CHANNEL, id="D", number=3, name="Off"),
        dict(CHANNEL, id="U", number=4, name="Unsub"),
    ]
    view = {"channels": channels, "subscribed": ["F", "S", "D"], "favourites": ["F"], "deactivated": ["D"], "ordered": False}
    monkeypatch.setattr(listing, "list_view", lambda call, scope=None: view)
    p.do_mychannels()
    rows = {li.label: (url, li) for url, li in added}
    # What holds of it beside the name, grey and italic; the name grey where it does not play.
    fav = "Fav  [I][COLOR grey]Favourite[/COLOR][/I]"
    off = "[COLOR grey]Off[/COLOR]  [I][COLOR grey]Deactivated[/COLOR][/I]"
    unsub = "[COLOR grey]Unsub[/COLOR]  [I][COLOR grey]Not available[/COLOR][/I]"
    assert set(rows) == {fav, "Sub", off, unsub}
    # The strongest state's icon (deactivated > favourite > not subscribed); no thumb: the row draws the icon.
    assert rows[fav][1].art == {"poster": "logo.png", "icon": "DefaultFavourites.png"}
    assert rows[off][1].art["icon"] == "DefaultAddonNone.png" and rows[unsub][1].art["icon"] == "DefaultAddonTvInfo.png"
    assert rows["Sub"][1].art["icon"] == "DefaultTVShows.png"  # a plain one's (Kodi's own would be a video's)
    assert [rows[label][1].getVideoInfoTag()["ProductionCode"] for label in (fav, "Sub", off, unsub)] == [
        "0000",
        "0001",
        "0002",
        "0003",
    ]
    assert all(li.properties["hide_add_remove_favourite"] == "true" for _, li in added)
    assert all(li.properties["IsPlayable"] == "false" and "action=channel_menu" in url for url, li in added)
    assert all("Title" not in li.getVideoInfoTag() for _, li in added)  # nor here: nothing plays in My channels
    labels = [[label for label, _ in menu] for menu in menus]
    assert labels[0] == ["Move...", "Remove from favourites", "Deactivate"]
    assert labels[2] == ["Move...", "Add to favourites", "Activate"]
    assert labels[3] == ["Move...", "Add to favourites"]  # not subscribed: nothing to deactivate
    assert not any("PlayMedia" in action or "action=play" in action for menu in menus for _, action in menu)

    # A click: the menu, then what was chosen (here: deactivate "Sub"), and the list made again.
    url = rows["Sub"][0]
    click = plugin.Plugin(["plugin://plugin.video.simplego/", "-1", "?" + url.split("?", 1)[1]])
    kodi.ANSWERS["contextmenu"] = 2
    click.run()
    assert channellist.deactivated() == {"S"}
    assert ("Channel deactivated", "notification") in kodi.LOG and ("Container.Refresh", "builtin") in kodi.LOG
    assert kodiutil.EXPORT_REQUEST not in kodi.PROPERTIES  # the lists' alone: Kodi TV hides channels itself

    # Run as Kodi's own Play would (a handle): Kodi is told at once that nothing plays.
    resolved = []
    monkeypatch.setattr(xbmcplugin, "setResolvedUrl", lambda handle, ok, li: resolved.append(ok), raising=False)
    kodi.ANSWERS["contextmenu"] = -1
    plugin.Plugin(["plugin://plugin.video.simplego/", "5", "?" + url.split("?", 1)[1]]).run()
    assert resolved == [False]


def test_a_list_change_redraws_the_list_and_leaves_kodi_tv_to_the_schedule(kodi, monkeypatch):
    """Favourites and the channel order are no settings change: no export right away."""
    from resources.lib import plugin

    changed = []

    class Client:
        def set_favourite_channel(self, number, on):
            changed.append(("favourite", number, on))

        def set_channel_order(self, order):
            changed.append(("order", order))

    monkeypatch.setattr(clientfactory, "make_client", Client)
    kodi.ANSWERS["yesno"] = True
    plugin.Plugin(["plugin://plugin.video.simplego/", "-1", "?action=favourite&number=8&on=1"]).run()
    plugin.Plugin(["plugin://plugin.video.simplego/", "-1", "?action=reset_order"]).run()
    assert changed == [("favourite", "8", True), ("order", [])]
    assert kodiutil.EXPORT_REQUEST not in kodi.PROPERTIES
    assert [m for m, kind in kodi.LOG if kind == "builtin"] == ["Container.Refresh", "Container.Refresh"]


def test_moving_a_channel_puts_it_before_the_one_picked(kodi):

    class Account:
        order = ["B", "A"]  # the account's own; C is new to it
        saved = []

        def channel_list(self, scope=None):
            return [dict(CHANNEL, id=i, number=n, name=i) for i, n in (("A", 1), ("B", 2), ("C", 3))]

        def channel_order(self):
            return self.order

        def set_channel_order(self, order):
            self.saved.append(order)

    client = Account()
    p = mychannels.MyChannelsViews(call("?action=move&id=C", "-1", client=client))
    p.do_move()  # the picker closed: nothing moves
    assert client.saved == []
    kodi.ANSWERS["select"] = 1  # before A (the rows: "2. B", "1. A", "To the end")
    p.do_move()
    assert client.saved == [["B", "C", "A"]] and ("Container.Refresh", "builtin") in kodi.LOG
    kodi.ANSWERS["select"] = 2  # to the end
    p.do_move()
    assert client.saved[-1] == ["B", "A", "C"]
