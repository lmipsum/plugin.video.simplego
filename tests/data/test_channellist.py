"""The channel lists' default order and what a deactivated channel shows."""

from resources.lib.data import channellist


def test_the_lists_default_order_and_a_deactivated_channel_without_its_programme(kodi, monkeypatch, tmp_path):
    """Favourites, the other subscribed, the deactivated, the unsubscribed: each group in the account's order."""
    monkeypatch.setattr(channellist, "DEACTIVATED", str(tmp_path / "deactivated.json"))
    assert channellist.deactivated() == set()
    channellist.set_deactivated(4, True)
    channellist.set_deactivated("2", True)
    channellist.set_deactivated(2, False)
    assert channellist.deactivated() == {"4"}  # kept as text: ids come as numbers or text

    def ch(n):
        return {"id": n, "station_id": "s%d" % n, "name": "C%d" % n}

    channels = [ch(n) for n in range(1, 8)]  # the account's order
    subscribed, favourites = {1, 2, 3, 4, 5}, [3, 4, 7]  # 7: an unsubscribed favourite, 4: a deactivated one
    order = [c["id"] for c in channellist.grouped(channels, subscribed, favourites, {"4", "5"})]
    assert order == [3, 1, 2, 4, 5, 6, 7]
    assert [c["id"] for c in channellist.grouped(channels, None, None, set())] == list(range(1, 8))  # the public list

    class Client:
        authed = True
        guided = 0

        def channel_list(self, scope="all", kind="all"):
            return [c for c in channels if scope != "favourite" or c["id"] in favourites]

        def channel_order(self):
            return []

        def subscribed_ids(self):
            return subscribed

        def now_and_next(self, blocks):
            self.guided += 1
            return {c["station_id"]: ({"description": "on %d" % c["id"]}, None) for c in channels}

    monkeypatch.setattr(channellist.parental, "hides_adult", lambda client: False)
    client = Client()
    view = channellist.view(client)
    assert [c["id"] for c in view["channels"]] == [3, 1, 2, 5, 4, 6, 7] and view["deactivated"] == ["4"]
    # No programme for a deactivated channel, nor for one outside the subscription.
    assert "s4" not in view["now"] and "s6" not in view["now"] and "s1" in view["now"]
    managed = channellist.view(client, channellist.MANAGE)
    assert client.guided == 1 and managed["now"] == {}  # My channels reads no guide
