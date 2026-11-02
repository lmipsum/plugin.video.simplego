"""An airing no longer watched back: its series (or the film itself) offered onto the favourite programmes."""

from kodiside import continue_at

from resources.lib.data import channellist
from resources.lib.data import onair
from resources.lib.data import watchoffer

EPISODE = {"description": "Doktor Balaton", "series_id": "S1", "program_id": "P1", "genres": [{"name": "Sorozatok"}]}
FILM = {"description": "Indiana Jones és az utolsó kereszteslovag", "program_id": "P2", "show_type": "Movie"}
LATER = {"station_id": "1246", "start_utc": "2099-11-05T19:00:00Z"}


class Client:
    def __init__(self, favourites=(), coming=(LATER,)):
        self.favourites = [{"id": i} for i in favourites]
        self.coming = list(coming)
        self.asked = []

    def station_of(self, channel_id):
        return "1246"

    def watchlist(self):
        return self.favourites

    def airings(self, item_id, kind="series"):
        self.asked.append((item_id, kind))
        return [], self.coming

    def bookmarks(self, details=False):
        return [{"id": "1246_2026-10-29T13:50:00Z_2026-10-29T16:20:00Z"}]


def guide(monkeypatch, programme):
    asked = []
    monkeypatch.setattr(onair, "on_air", lambda client, station, when: asked.append((station, when)) or (programme, None))
    monkeypatch.setattr(channellist, "by_station", lambda client: {"1246": {"name": "Mozi+ HD"}})
    monkeypatch.setattr(watchoffer.kodiutil, "local_time", lambda iso: "2099.11.05. 20:00")
    return asked


def test_a_series_is_offered_as_a_whole_and_a_film_itself_with_its_next_airing(monkeypatch):
    asked = guide(monkeypatch, EPISODE)
    client = Client()
    offered = watchoffer.offer(client, "18569", "2026-10-29T13:50:00Z")
    assert offered == {"id": "S1", "kind": "series", "title": "Doktor Balaton", "next": "2099.11.05. 20:00, Mozi+ HD"}
    assert asked == [("1246", "2026-10-29T13:50:00Z")] and client.asked == [("S1", "series")]
    guide(monkeypatch, FILM)
    assert watchoffer.offer(Client(), "18569", "2026-10-29T13:50:00Z")["id"] == "P2"


def test_nothing_is_offered_that_is_a_favourite_already_unknown_or_not_on_again(monkeypatch):
    guide(monkeypatch, FILM)
    assert watchoffer.offer(Client(favourites=["P2"]), "18569", "2026-10-29T13:50:00Z") is None
    # No airing to come, or only on a channel outside the subscription: the provider would not keep it.
    assert watchoffer.offer(Client(coming=()), "18569", "2026-10-29T13:50:00Z") is None
    elsewhere = dict(LATER, station_id="9999")
    assert watchoffer.offer(Client(coming=[elsewhere]), "18569", "2026-10-29T13:50:00Z") is None
    gone = dict(LATER, start_utc="2001-01-01T00:00:00Z")
    assert watchoffer.offer(Client(coming=[gone]), "18569", "2026-10-29T13:50:00Z") is None
    guide(monkeypatch, None)  # not in the guide
    assert watchoffer.offer(Client(), "18569", "2026-10-29T13:50:00Z") is None


def test_a_play_address_without_a_programme_offers_nothing(monkeypatch):
    guide(monkeypatch, FILM)
    assert watchoffer.offer_for_play(Client(), "18569", None) is None
    assert watchoffer.offer_for_play(Client(), "18569", "2026-10-29T13:50:00Z~2026-10-29T16:20:00Z~ct~12~start")["id"] == "P2"


def test_with_no_favourite_to_offer_its_continue_watching_row_is_offered_off_the_list(monkeypatch, tmp_path):
    continue_at(monkeypatch, tmp_path)
    guide(monkeypatch, FILM)
    play = "2026-10-29T13:50:00Z~2026-10-29T16:20:00Z~ct~12~start"
    # Not on again: the row instead (the account's position here).
    assert watchoffer.offer_for_play(Client(coming=()), "18569", play) == {
        "mark": "1246_2026-10-29T13:50:00Z_2026-10-29T16:20:00Z"
    }
    # A favourite already, and not in Continue watching: nothing to offer.
    other = play.replace("13:50", "10:00")
    assert watchoffer.offer_for_play(Client(favourites=["P2"]), "18569", other) is None
