"""Continue watching as kept here: watched and reset rows until they leave catch-up."""

from kodiside import continue_at


def test_continue_watching_keeps_watched_and_reset_rows_greyed_until_they_leave_catch_up(monkeypatch, tmp_path):
    continuelist = continue_at(monkeypatch, tmp_path)
    ACTIVE, WATCHED, REMOVED = continuelist.ACTIVE, continuelist.WATCHED, continuelist.REMOVED

    def mark(n, share=0.5, end="2026-10-28T21:00:00Z"):
        return {"id": "1_2026-10-28T20:0%d:00Z_%s" % (n, end), "time_seconds": 3600 * share, "runtime_seconds": 3600}

    old = mark(9, end="2026-10-21T21:00:00Z")  # left catch-up a day ago
    assert continuelist.rows([mark(1), mark(2), mark(3, share=0.95), old]) == [
        (mark(1), ACTIVE),
        (mark(2), ACTIVE),
        (mark(3, share=0.95), WATCHED),  # from 90% on, as Kodi counts it
    ]
    continuelist.set_removed(mark(2))  # reset here: gone from the account's list
    # Gone from the list without a reset here: watched to its end (the provider's apps remove none).
    assert continuelist.rows([mark(3, share=0.95)]) == [(mark(3, share=0.95), WATCHED), (mark(1), WATCHED), (mark(2), REMOVED)]
    # Back in the list (watched again): active again; the greyed ones below.
    assert continuelist.rows([mark(2)])[0] == (mark(2), ACTIVE)
    # A week after the programme ended: no longer listed, nor kept.
    later = continue_at(monkeypatch, tmp_path, now="2026-11-04T21:00:01Z")
    assert later.rows([]) == [] and later._load() == {}


def test_a_row_is_found_by_its_airing_and_dropped_for_good(monkeypatch, tmp_path):
    continuelist = continue_at(monkeypatch, tmp_path)
    mark = {"id": "1_2026-10-28T20:00:00Z_2026-10-28T21:00:00Z", "time_seconds": 600, "runtime_seconds": 3600}
    assert continuelist.find("1", "2026-10-28T20:00:00Z", [mark]) == mark  # the account's position
    continuelist.rows([mark])
    assert continuelist.find("1", "2026-10-28T20:00:00Z", []) == mark  # a greyed row kept here
    assert continuelist.find("2", "2026-10-28T20:00:00Z", []) is None
    continuelist.drop(mark["id"])
    assert continuelist.rows([]) == [] and continuelist.find("1", "2026-10-28T20:00:00Z", []) is None


def test_a_row_is_on_catch_up_while_its_airing_is_among_its_programmes():
    from resources.lib.data import continuelist

    mark = {"id": "1246_2026-10-29T13:50:00Z_2026-10-29T16:20:00Z"}
    later = {"station_id": "1246", "start_utc": "2026-11-01T20:00:00Z"}
    assert continuelist.on_catchup(mark, [later, {"station_id": 1246, "start_utc": "2026-10-29T13:50:00Z"}])
    assert not continuelist.on_catchup(mark, [later])  # gone from catch-up; the programme's later airing is another
    assert not continuelist.on_catchup({"id": "film"}, [later])  # no airing to tell by
