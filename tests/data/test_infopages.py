"""The programmes' info pages, fetched once and kept a month: the lists' plot, type, year and cast, the export's credits."""

import json
import time

from kodiside import GuideClient

from resources.lib.data import infopages

MOVIE = {"program_id": "M1", "show_type": "Movie"}
EPISODE = {"program_id": "E1", "series_id": "S1", "genres": [{"name": "Sorozatok"}]}
EXPORT_PAGES = {
    ("program", "M1"): {
        "details": {"description": "A treasure hunt."},
        "roles": [
            {"role_name": "Színész", "person_name": "Some Actor"},
            {"role_name": "Rendező", "person_name": "Some Director"},
            {"role_name": "Producer", "person_name": "Not wanted"},
        ],
    },
    ("series", "S1"): {"details": {}, "roles": [{"role_name": "Színész", "person_name": "Another Actor"}]},
}


def _export_cast(tmp_path):
    """Fetch the export's cast of a movie and two episodes of a series; the client asked and what was kept."""
    client = GuideClient(pages=EXPORT_PAGES)
    progs = [MOVIE, EPISODE, dict(EPISODE, program_id="E2")]
    keys = [k for p in progs for k in infopages.keys_of(p)]
    return client, infopages.info_for(client, keys, str(tmp_path))


def test_the_export_asks_a_series_page_once_for_all_its_episodes(tmp_path):
    client, _ = _export_cast(tmp_path)
    # The plots come with the guide.
    assert sorted(client.asked) == [("program", "M1"), ("series", "S1")]


def test_the_export_takes_the_actors_and_directors(tmp_path):
    _, cache = _export_cast(tmp_path)
    assert infopages.programme_credits(MOVIE, cache) == {"actor": ["Some Actor"], "director": ["Some Director"]}
    assert infopages.programme_credits(EPISODE, cache) == {"actor": ["Another Actor"]}


def test_the_next_export_fetches_nothing_new_and_drops_what_left_the_guide(tmp_path):
    client, _ = _export_cast(tmp_path)
    client.asked.clear()
    assert list(infopages.info_for(client, infopages.keys_of(MOVIE), str(tmp_path))) == [("program", "M1")] and client.asked == []


LIST_KEYS = [("program", "P1"), ("program", "P2"), ("series", "S1"), ("program", None)]


def _plot_pages():
    return {key: {"details": {"description": "Plot of %s " % key[1]}} for key in LIST_KEYS if key[1]}


def _plots_for_the_list(tmp_path):
    """The list's plots asked for, one of them kept as it started playing; the client and what it gave."""
    client = GuideClient(pages=_plot_pages())
    infopages.keep_plot("P1", "Watched back here.", str(tmp_path))
    return client, infopages.pages_for(client, LIST_KEYS, str(tmp_path), full=False)


def test_for_a_plot_alone_the_one_kept_from_the_guide_will_do(tmp_path):
    client, pages = _plots_for_the_list(tmp_path)
    assert {key: page["plot"] for key, page in pages.items()} == {
        ("program", "P1"): "Watched back here.",
        ("program", "P2"): "Plot of P2",
        ("series", "S1"): "Plot of S1",
    }
    assert sorted(client.asked) == [("program", "P2"), ("series", "S1")]


def test_for_the_whole_page_only_the_one_with_a_kept_plot_alone_is_fetched(tmp_path):
    client, _ = _plots_for_the_list(tmp_path)
    assert infopages.pages_for(client, LIST_KEYS, str(tmp_path))[("program", "P2")]["type"] == "other"
    assert sorted(client.asked) == [("program", "P1"), ("program", "P2"), ("series", "S1")]


def test_a_page_not_asked_for_in_a_month_goes(tmp_path):
    client, _ = _plots_for_the_list(tmp_path)
    infopages.pages_for(client, LIST_KEYS, str(tmp_path))
    path = tmp_path / infopages.PAGE_CACHE
    kept = json.loads(path.read_text(encoding="utf-8"))
    kept["program/P1"]["used"] = time.time() - infopages.PAGE_KEPT - 1
    path.write_text(json.dumps(kept), encoding="utf-8")
    infopages.pages_for(client, [("program", "P2")], str(tmp_path))
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"program/P2", "series/S1"}


LIST_PAGES = {
    ("program", "M1"): {
        "show_type": "Movie",
        "release_year": 1972,
        "details": {"description": "Plot."},
        "roles": [{"role_name": "Színész", "person_name": "Some Actor"}, {"role_name": "Producer", "person_name": "X"}],
    },
    ("series", "S1"): {
        "show_type": "TVShow",
        "details": {"metadata": [{"type": "GENRES", "value": "Vígjáték,Sorozatok"}]},
        "roles": [{"role_name": "Rendező", "person_name": "Some Director"}],
    },
}


def test_one_request_per_page_gives_the_lists_plot_type_year_and_cast(tmp_path):
    client = GuideClient(pages=LIST_PAGES)
    got = infopages.pages_for(lambda: client, list(LIST_PAGES), str(tmp_path))
    movie = got[("program", "M1")]
    assert (movie["plot"], movie["type"], movie["year"], movie["actor"]) == ("Plot.", "movie", 1972, ["Some Actor"])
    assert got[("series", "S1")]["type"] == "series" and got[("series", "S1")]["director"] == ["Some Director"]
    # The export takes the roles only.
    assert infopages.programme_credits({"program_id": "M1", "show_type": "Movie"}, got) == {"actor": ["Some Actor"]}


def test_pages_asked_again_need_no_client_and_leave_the_exports_file_alone(tmp_path):
    client = GuideClient(pages=LIST_PAGES)
    infopages.pages_for(lambda: client, list(LIST_PAGES), str(tmp_path))
    client.asked.clear()
    made = []
    assert infopages.pages_for(lambda: made.append(1) or client, [("program", "M1")], str(tmp_path))
    assert client.asked == [] and made == [] and not (tmp_path / infopages.INFO_CACHE).exists()


def test_an_airings_episode_numbers_come_from_its_info_page(tmp_path):
    pages = {("program", "E1"): {"season_number": "2", "episode_number": 5}, ("program", "F1"): {"show_type": "Movie"}}
    assert infopages.episode_numbers(GuideClient(pages=pages), ["E1", "F1", None], str(tmp_path)) == {"E1": (2, 5)}
