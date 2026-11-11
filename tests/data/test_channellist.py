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


def test_a_channel_is_deactivated_by_its_id_as_number_or_text():
    assert channellist.is_deactivated(4, {"4"}) and channellist.is_deactivated("4", {"4"})
    assert not channellist.is_deactivated(2, {"4"})


def test_after_a_refused_login_the_public_channels_are_listed_as_a_guest(kodi):
    class Client:
        guest = False

        @property
        def authed(self):
            return not self.guest

        def channel_list(self, scope="all", kind="all"):
            return [{"id": 1, "station_id": "s1", "name": "C1"}]

        def now_and_next(self, blocks):
            return {}

    client = Client()
    view = channellist.public_view(client)
    assert client.guest and view["subscribed"] is None and view["favourites"] is None
    assert [c["id"] for c in view["channels"]] == [1]
