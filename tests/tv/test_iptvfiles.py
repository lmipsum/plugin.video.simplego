"""The TV export: the playlist and the guide IPTV Simple reads, each block's XML made again only when it changed."""

import calendar
import gzip
import json
import os
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import pytest
from kodiside import GuideClient

from resources.lib.data import guidedata
from resources.lib.data import infopages
from resources.lib.tv import iptvfiles

CHANNELS = [
    {
        "id": "11",
        "station_id": "1001",
        "name": 'Channel "One"',
        "number": 1,
        "logo": "https://logo/1.png",
        "radio": False,
        "media_id": "LIVE$11",
        "genres": ["Sport", "Hír; info"],
    },
    {"id": "22", "station_id": "1002", "name": "Radio Two", "number": 2, "logo": "", "radio": True, "media_id": "LIVE$22"},
]

PROGRAMMES = {
    "1001": [
        {
            "start_time": "2026-10-25T17:55:00Z",
            "end_time": "2026-10-25T18:30:00Z",
            "description": "Title & Co",
            "episode_name": "Episode <1>",
            "full_description": "Plot",
            "genres": [{"name": "Drama"}, {"name": ""}],
            "season_number": 2,
            "episode_number": "5",
            "program_id": "ABC-123",
        }
    ],
    "9999": [{"start_time": "2026-10-25T00:00:00Z", "end_time": "2026-10-25T01:00:00Z", "description": "x"}],
}
CAST = ("movie", "series", "other")
PAGE = {"details": {}, "roles": [{"role_name": "Színész", "person_name": "Some Actor"}]}


def _client(programmes=PROGRAMMES, pages=None):
    """A client whose guide is one block of these programmes."""
    return GuideClient((None, None, programmes), pages=pages)


def _two_blocks(late_title="Late"):
    """Two blocks; the early programme runs into the second block too, so it is in the guide once."""
    early = dict(PROGRAMMES["1001"][0], start_time="2026-10-25T00:10:00Z", end_time="2026-10-25T03:30:00Z")
    late = dict(PROGRAMMES["1001"][0], start_time="2026-10-25T03:30:00Z", end_time="2026-10-25T04:00:00Z", description=late_title)
    return [("2026-10-25", 0, {"1001": [early]}), ("2026-10-25", 3, {"1001": [early, late]})]


def _channel_lines(tmp_path):
    """The playlist's lines without its group order lines (see iptvfiles.export)."""
    lines = (tmp_path / "iptv" / "channels.m3u").read_text(encoding="utf-8").splitlines()
    return [line for line in lines if not line.startswith("#EXTGRP")]


def _guide_text(tmp_path):
    with gzip.open(str(tmp_path / "iptv" / iptvfiles.GUIDE)) as f:
        return f.read().decode("utf-8")


def _guide_root(tmp_path):
    with gzip.open(str(tmp_path / "iptv" / iptvfiles.GUIDE)) as f:
        return ET.parse(f).getroot()


def plugin_url(**kw):
    return "plugin://plugin.video.simplego/?action=%s&id=%s&media=%s" % (kw["action"], kw["id"], kw["media"])


def test_export_writes_the_playlist(tmp_path):
    assert iptvfiles.export(_client(), CHANNELS, str(tmp_path), plugin_url) == (2, 1)
    m3u = _channel_lines(tmp_path)
    assert m3u[0] == "#EXTM3U"
    assert 'tvg-id="simplego.1001"' in m3u[1] and "tvg-name=\"Channel 'One'\"" in m3u[1]
    assert 'group-title="Simple GO;Sport;Hír, info"' in m3u[1]
    assert 'group-title="Simple GO"' in m3u[3]
    assert m3u[2] == "plugin://plugin.video.simplego/?action=play&id=11&media=LIVE$11"
    assert 'radio="true"' in m3u[3] and 'radio="true"' not in m3u[1]


def test_export_writes_the_guide(tmp_path):
    iptvfiles.export(_client(), CHANNELS, str(tmp_path), plugin_url)
    root = _guide_root(tmp_path)
    assert [c.get("id") for c in root.findall("channel")] == ["simplego.1001", "simplego.1002"]
    (prog,) = root.findall("programme")  # the unknown station 9999 is skipped
    assert prog.get("start") == "20261025175500 +0000"
    assert prog.get("stop") == "20261025183000 +0000"
    assert prog.find("title").text == "Title & Co"
    assert prog.find("sub-title").text == "Episode <1>"
    # "Drama" is not a provider category, so the channel's ("Sport") comes first for the colour.
    assert [c.text for c in prog.findall("category")] == ["Sport", "Drama"]
    assert prog.find("episode-num").text == "1.4."
    assert prog.find("icon").get("src").endswith("/program/abc-123/16x9/keyartmedium.jpg")


def _export_twice(tmp_path, channels=CHANNELS):
    """Export, make the guide look written a second earlier, export again with these channels; the stats, the guide's time."""
    iptvfiles.export(_client(), CHANNELS, str(tmp_path), plugin_url)
    guide = tmp_path / "iptv" / iptvfiles.GUIDE
    earlier = guide.stat().st_mtime_ns - 10**9
    os.utime(str(guide), ns=(earlier, earlier))
    stats = {}
    assert iptvfiles.export(_client(), channels, str(tmp_path), plugin_url, stats=stats) == (2, 1)
    return stats, earlier


def test_an_export_with_nothing_new_rewrites_nothing(tmp_path):
    stats, earlier = _export_twice(tmp_path)
    assert stats.get("unchanged") and (tmp_path / "iptv" / iptvfiles.GUIDE).stat().st_mtime_ns == earlier


def test_an_export_with_a_channel_renamed_writes_the_guide_again(tmp_path):
    stats, _ = _export_twice(tmp_path, [dict(CHANNELS[0], name="Other")] + CHANNELS[1:])
    assert not stats.get("unchanged") and "Other" in _guide_text(tmp_path)


def test_only_the_blocks_that_changed_are_made_again(tmp_path):
    client, stats = GuideClient(*_two_blocks()), {}
    assert iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, stats=stats) == (2, 2)
    assert stats["rendered"] == 2
    client.blocks, stats = _two_blocks("Changed"), {}
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, stats=stats)
    assert stats["rendered"] == 1  # the first block's XML is kept
    titles = [p.find("title").text for p in _guide_root(tmp_path).findall("programme")]
    assert sorted(titles) == ["Changed", "Title & Co"]
    assert len(os.listdir(str(tmp_path / "iptv" / iptvfiles.XML_DIR))) == 2  # the old second block's is gone


def _cast_client(tmp_path):
    """A client of two blocks with a cast, exported once with it."""
    client = GuideClient(*_two_blocks(), pages={("program", "ABC-123"): PAGE})
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, info_types=CAST)
    return client


def test_with_the_cast_its_page_is_asked_once(tmp_path):
    stats = {}
    client = GuideClient(*_two_blocks(), pages={("program", "ABC-123"): PAGE})
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, info_types=CAST, stats=stats)
    assert stats["read"] == 2 and client.asked == [("program", "ABC-123")]
    assert "Some Actor" in _guide_text(tmp_path)


def test_with_the_cast_an_unchanged_block_is_not_read_again(tmp_path):
    """Its info page keys are kept: reading every block twice was most of an export with nothing new."""
    client, stats = _cast_client(tmp_path), {}
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, info_types=CAST, stats=stats)
    assert stats["read"] == 0 and stats.get("unchanged") and client.asked == [("program", "ABC-123")]


def test_with_the_cast_only_a_changed_block_is_read_and_made_again(tmp_path):
    client, stats = _cast_client(tmp_path), {}
    client.blocks = _two_blocks("Changed")
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, info_types=CAST, stats=stats)
    assert stats["read"] == 1 and stats["rendered"] == 1
    assert _guide_text(tmp_path).count("Some Actor") == 2  # the kept block's and the one made again
    with open(str(tmp_path / "iptv" / iptvfiles.KEYS), encoding="utf-8") as f:
        assert len(json.load(f)) == 2  # this export's blocks only: the file does not grow


def test_without_the_cast_no_block_is_read_for_its_keys(tmp_path):
    client, stats = _cast_client(tmp_path), {}
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, stats=stats)
    assert "read" not in stats


def test_genre_map_and_category_order(tmp_path):
    progs = {
        "1001": [
            {
                "start_time": "2026-10-25T17:55:00Z",
                "end_time": "2026-10-25T18:30:00Z",
                "description": "x",
                "genres": [{"name": "Sorozatok"}, {"name": "Vígjáték"}],
            }
        ]
    }
    iptvfiles.export(_client(progs), CHANNELS[:1], str(tmp_path), plugin_url)
    mapping = ET.parse(str(tmp_path / "iptv" / iptvfiles.GENRE_MAP)).getroot()
    ids = {g.text: int(g.get("genreId"), 16) for g in mapping.findall("genre")}
    assert ids["Vígjáték"] == 0x14 and ids["Labdarúgás"] == 0x43 and ids["Hír- és politikai műsorok"] == 0x20
    prog = _guide_root(tmp_path).find("programme")
    # The broad "Sorozatok" goes last, so IPTV Simple colours this one as a comedy.
    assert [c.text for c in prog.findall("category")] == ["Vígjáték", "Sorozatok"]


def test_the_guide_without_category_colours_has_a_mapping_of_its_own():
    assert "<genre " not in iptvfiles.genre_map(colours=False) and "<genre " in iptvfiles.genre_map()


@pytest.mark.parametrize(
    ("channel_genre", "names", "categories"),
    [
        ("Gyerekeknek", (), ["Gyerekeknek"]),  # no category of its own
        ("Gyerekeknek", ("Sorozatok",), ["Gyerekeknek", "Sorozatok"]),  # only a broad one
        ("Gyerekeknek", ("Egyéb", "Ismeretlen"), ["Gyerekeknek", "Ismeretlen", "Egyéb"]),
        ("Gyerekeknek", ("Sorozatok", "Vígjáték"), ["Vígjáték", "Sorozatok"]),  # its own wins
        (None, ("Sorozatok",), ["Sorozatok"]),  # a channel of mixed content adds nothing
    ],
)
def test_channel_category_colours_programmes_without_their_own(channel_genre, names, categories):
    prog = {"start_time": "2026-10-25T00:00:00Z", "end_time": "2026-10-25T01:00:00Z", "genres": [{"name": n} for n in names]}
    xml = iptvfiles._programme("c", prog, channel_genre)
    assert [c.text for c in ET.fromstring(xml).findall("category")] == categories


def _programme(**extra):
    prog = dict({"start_time": "2026-10-25T00:00:00Z", "end_time": "2026-10-25T01:00:00Z"}, **extra)
    return ET.fromstring(iptvfiles._programme("c", prog))


def test_a_movie_has_its_year_and_age_rating():
    p = _programme(release_year="1997", show_type="Movie", ratings="16+")
    assert p.find("date").text == "1997" and p.find("rating/value").text == "16"


def test_only_movies_and_numbered_episodes_have_a_year():
    # Trakt would take a news programme with a year for a movie.
    assert _programme(release_year="2026", show_type="TVShow").find("date") is None
    assert _programme(release_year="1982", show_type="TVShow", season_number=1, episode_number=3).find("date").text == "1982"


def test_an_age_rating_without_a_plus():
    assert _programme(ratings="18").find("rating/value").text == "18"


def test_no_year_and_no_age_limit_leave_them_out():
    p = _programme(release_year=None, ratings="0-99")
    assert p.find("date") is None and p.find("rating") is None


def test_a_programme_has_the_plot_from_the_guide_and_the_cast_from_its_info_page(tmp_path):
    movie = {"program_id": "M1", "show_type": "Movie"}
    page = {
        "details": {},
        "roles": [
            {"role_name": "Színész", "person_name": "Some Actor"},
            {"role_name": "Rendező", "person_name": "Some Director"},
        ],
    }
    cache = infopages.info_for(GuideClient(pages={("program", "M1"): page}), infopages.keys_of(movie), str(tmp_path))
    times = {"start_time": "2026-10-25T00:00:00Z", "end_time": "2026-10-25T01:00:00Z", "full_description": "A treasure hunt."}
    prog = ET.fromstring(iptvfiles._programme("c", dict(movie, **times), None, infopages.programme_credits(movie, cache)))
    assert prog.find("desc").text == "A treasure hunt."
    assert prog.find("credits/director").text == "Some Director" and prog.find("credits/actor").text == "Some Actor"


def test_export_reports_its_progress(tmp_path):
    class Reporting(GuideClient):
        def epg_blocks(self, progress=None, **kw):
            progress(1, 2)
            progress(2, 2)
            return super().epg_blocks(**kw)

    stages, stats = [], {}
    iptvfiles.export(
        Reporting((None, None, PROGRAMMES)),
        CHANNELS,
        str(tmp_path),
        plugin_url,
        progress=lambda *a: stages.append(a),
        stats=stats,
    )
    assert stages == [("guide", 1, 2), ("guide", 2, 2), ("build", 0, 1), ("build", 1, 1), ("compress",)]
    assert {"guide", "info", "write"} <= set(stats)


def test_a_cancelled_export_writes_no_file(tmp_path):
    def cancel(stage, *a):
        if stage == "compress":
            raise iptvfiles.Cancelled()

    with pytest.raises(iptvfiles.Cancelled):
        iptvfiles.export(_client(), CHANNELS, str(tmp_path), plugin_url, progress=cancel)
    # Only the blocks' XML made so far is kept, for the next time.
    assert os.listdir(str(tmp_path / "iptv")) == [iptvfiles.XML_DIR]


def _catchup_export(tmp_path):
    channels = [dict(CHANNELS[0], catchup=True), CHANNELS[1]]
    first = dict(PROGRAMMES["1001"][0], content_flags=["ct", "fw"])
    later = dict(first, start_time="2026-10-25T19:00:00Z", end_time="2026-10-25T20:00:00Z", content_flags=["nb"])
    iptvfiles.export(
        _client({"1001": [first, later]}),
        channels,
        str(tmp_path),
        lambda **kw: "plugin://plugin.video.simplego/?" + urlencode(kw),
    )


def test_catchup_in_the_playlist(tmp_path):
    _catchup_export(tmp_path)
    m3u = _channel_lines(tmp_path)
    # IPTV Simple's placeholder stays as it is; the radio channel has no archive.
    # Days ignored: IPTV Simple offers just the programmes with a catchup-id.
    assert 'catchup="default" catchup-days="-1"' in m3u[1] and "programme={catchup-id}" in m3u[1]
    # IPTV Simple takes a line with "media=" in it for a recording, not a channel.
    assert "media=" not in m3u[1] and "media-dir=" not in m3u[1] and "media-size=" not in m3u[1]
    assert "catchup" not in m3u[3]


def test_catchup_in_the_guide(tmp_path):
    _catchup_export(tmp_path)
    prog, no_archive = _guide_root(tmp_path).findall("programme")
    assert no_archive.get("catchup-id") is None  # not in the archive ("ct"): not offered
    param = prog.get("catchup-id")
    assert param == "2026-10-25T17:55:00Z~2026-10-25T18:30:00Z~ct.fw~"  # no age rating
    parsed = guidedata.from_param(param)
    assert parsed["start"] == "2026-10-25T17:55:00Z" and parsed["flags"] == {"ct", "fw"}
    assert parsed["end"] == calendar.timegm((2026, 10, 25, 18, 30, 0))


def test_favourite_channels_are_a_group_of_their_own(tmp_path):
    channels = [CHANNELS[1], dict(CHANNELS[0], groups=["Kedvencek"])]
    iptvfiles.export(_client(), channels, str(tmp_path), plugin_url)
    m3u = (tmp_path / "iptv" / "channels.m3u").read_text(encoding="utf-8").splitlines()
    # The groups in order up front (then ended), the channels in their own order.
    assert m3u[1:3] == ["#EXTGRP:Simple GO;Kedvencek", "#EXTGRP:"]
    assert 'group-title="Simple GO"' in m3u[3]
    assert 'group-title="Simple GO;Kedvencek;Sport;Hír, info"' in m3u[5]


def test_the_export_may_hold_before_each_block_it_writes(tmp_path):
    paused, client = [], _client()
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, pause=lambda: paused.append(1))
    assert len(paused) == len(client.blocks)  # the fake client's own fetches do not call it
