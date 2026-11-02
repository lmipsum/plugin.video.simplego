"""The packages a channel outside the subscription is in."""


def test_the_package_offers_are_read_from_a_programmes_actions(monkeypatch):
    from resources.lib.provider import personal

    called = []

    class Auth:
        def call(self, path, flow, step, **kw):
            called.append(path)
            offer = {"package_name": "Telekom TV M csomag", "price": 6990}
            return {"actions": {"channel_subscribe": [{"channel_number": "33", "channel_subscribe": [offer, offer]}]}}

    mine = personal.Personal(state={}, api=None, auth=Auth(), channels=None)
    assert [o["package_name"] for o in mine.offers("31303031ThirdParty36383937353338")] == ["Telekom TV M csomag"] * 2
    assert called == ["/details/program/31303031ThirdParty36383937353338/actions/v2"]
