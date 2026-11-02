"""What the lists share: the channel list from the play service, else made here."""

from kodiside import call

from resources.lib.data import channellist
from resources.lib.views import listing


def test_a_list_the_service_cannot_give_is_made_here(monkeypatch):
    from resources.lib.service import quickplay

    made = []
    monkeypatch.setattr(quickplay, "ask", lambda path, timeout, **query: {"error": "api", "message": "busy"})
    monkeypatch.setattr(channellist, "view", lambda client, scope: made.append(scope) or {"channels": []})
    mychannels = call("?action=mychannels", client=object())
    assert listing.list_view(mychannels, channellist.MANAGE) == {"channels": []} and made == [channellist.MANAGE]
    monkeypatch.setattr(quickplay, "ask", lambda path, timeout, **query: {"channels": ["from the service"]})
    assert listing.list_view(mychannels, channellist.MANAGE) == {"channels": ["from the service"]}
    assert made == [channellist.MANAGE]
