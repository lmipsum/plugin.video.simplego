import calendar
import gzip
import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import pytest

from resources.lib.data import guidedata
from resources.lib.data import infopages
from resources.lib.provider.guideblocks import GuideBlock
from resources.lib.tv import iptvfiles
from resources.lib.tv import iptvsimple

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


def _blocks(*blocks):
    """The guide's blocks as Client.epg_blocks returns them, from (date, offset, programmes by station)."""
    return [(date, offset, GuideBlock(channels=channels)) for date, offset, channels in blocks]


class FakeClient:
    epg_stats = {}  # the guide's own count of blocks fetched and kept

    def epg_blocks(self, past_days=1, days_ahead=7, **kw):
        return _blocks((None, None, PROGRAMMES))


def _channel_lines(tmp_path):
    """The playlist's lines without its group order lines (see iptvfiles.export)."""
    lines = (tmp_path / "iptv" / "channels.m3u").read_text(encoding="utf-8").splitlines()
    return [line for line in lines if not line.startswith("#EXTGRP")]


def plugin_url(**kw):
    return "plugin://plugin.video.simplego/?action=%s&id=%s&media=%s" % (kw["action"], kw["id"], kw["media"])


def new_instance(folder, m3u, epg):
    """Return the settings of a new instance written for these files, by id."""
    os.makedirs(str(folder), exist_ok=True)
    assert iptvsimple.update_instance(str(folder), m3u, epg, create=True)
    return {s.get("id"): s.text for s in ET.parse(iptvsimple.instance_file(str(folder), m3u)).getroot()}


def test_export_writes_the_playlist_and_the_guide(tmp_path):
    n_channels, n_progs = iptvfiles.export(FakeClient(), CHANNELS, str(tmp_path), plugin_url)
    assert (n_channels, n_progs) == (2, 1)

    m3u = _channel_lines(tmp_path)
    assert m3u[0] == "#EXTM3U"
    assert 'tvg-id="simplego.1001"' in m3u[1] and "tvg-name=\"Channel 'One'\"" in m3u[1]
    assert 'group-title="Simple GO;Sport;Hír, info"' in m3u[1]
    assert 'group-title="Simple GO"' in m3u[3]
    assert m3u[2] == "plugin://plugin.video.simplego/?action=play&id=11&media=LIVE$11"
    assert 'radio="true"' in m3u[3] and 'radio="true"' not in m3u[1]

    with gzip.open(str(tmp_path / "iptv" / "epg.xml.gz")) as f:
        root = ET.parse(f).getroot()
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


def test_an_export_with_nothing_new_rewrites_nothing(tmp_path):
    stats = {}
    assert iptvfiles.export(FakeClient(), CHANNELS, str(tmp_path), plugin_url, stats=stats) == (2, 1)
    guide = tmp_path / "iptv" / iptvfiles.GUIDE
    written = guide.stat().st_mtime_ns
    os.utime(str(guide), ns=(written - 10**9, written - 10**9))
    stats = {}
    assert iptvfiles.export(FakeClient(), CHANNELS, str(tmp_path), plugin_url, stats=stats) == (2, 1)
    assert stats.get("unchanged") and guide.stat().st_mtime_ns == written - 10**9
    # Another channel name: written again.
    renamed = [dict(CHANNELS[0], name="Other")] + CHANNELS[1:]
    stats = {}
    iptvfiles.export(FakeClient(), renamed, str(tmp_path), plugin_url, stats=stats)
    assert not stats.get("unchanged") and "Other" in gzip.open(str(guide)).read().decode("utf-8")


def test_only_the_blocks_that_changed_are_made_again(tmp_path):
    early = dict(PROGRAMMES["1001"][0], start_time="2026-10-25T00:10:00Z", end_time="2026-10-25T03:30:00Z")
    late = dict(PROGRAMMES["1001"][0], start_time="2026-10-25T03:30:00Z", end_time="2026-10-25T04:00:00Z")

    class Client:
        late_title = "Late"

        epg_stats = {}  # the guide's own count of blocks fetched and kept

        def epg_blocks(self, **kw):
            # The early programme runs into the second block too: in the guide once.
            return _blocks(
                ("2026-10-25", 0, {"1001": [early]}),
                ("2026-10-25", 3, {"1001": [early, dict(late, description=self.late_title)]}),
            )

    client, stats = Client(), {}
    assert iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, stats=stats) == (2, 2)
    assert stats["rendered"] == 2
    client.late_title, stats = "Changed", {}
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, stats=stats)
    assert stats["rendered"] == 1  # the first block's XML is kept
    with gzip.open(str(tmp_path / "iptv" / iptvfiles.GUIDE)) as f:
        titles = [p.find("title").text for p in ET.parse(f).getroot().findall("programme")]
    assert sorted(titles) == ["Changed", "Title & Co"]
    assert len(os.listdir(str(tmp_path / "iptv" / iptvfiles.XML_DIR))) == 2  # the old second block's is gone


def test_with_the_cast_an_unchanged_block_is_not_read_again(tmp_path):
    """Its info page keys are kept: reading every block twice was most of an export with nothing new."""
    early = dict(PROGRAMMES["1001"][0], start_time="2026-10-25T00:10:00Z", end_time="2026-10-25T03:30:00Z")
    late = dict(PROGRAMMES["1001"][0], start_time="2026-10-25T03:30:00Z", end_time="2026-10-25T04:00:00Z")
    page = {"details": {}, "roles": [{"role_name": "Színész", "person_name": "Some Actor"}]}

    class Client:
        late_title = "Late"
        asked = []

        epg_stats = {}  # the guide's own count of blocks fetched and kept

        def epg_blocks(self, **kw):
            return _blocks(
                ("2026-10-25", 0, {"1001": [early]}),
                ("2026-10-25", 3, {"1001": [early, dict(late, description=self.late_title)]}),
            )

        def details(self, kind, item_id):
            self.asked.append((kind, item_id))
            return page

    client, cast = Client(), ("movie", "series", "other")
    stats = {}
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, info_types=cast, stats=stats)
    assert stats["read"] == 2 and client.asked == [("program", "ABC-123")]
    assert "Some Actor" in gzip.open(str(tmp_path / "iptv" / iptvfiles.GUIDE)).read().decode("utf-8")
    # Nothing new: no block read, nothing rewritten, no page asked again.
    stats = {}
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, info_types=cast, stats=stats)
    assert stats["read"] == 0 and stats.get("unchanged") and client.asked == [("program", "ABC-123")]
    # One block changed: only it is read, and only its XML made again.
    client.late_title, stats = "Changed", {}
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, info_types=cast, stats=stats)
    assert stats["read"] == 1 and stats["rendered"] == 1
    guide = gzip.open(str(tmp_path / "iptv" / iptvfiles.GUIDE)).read().decode("utf-8")
    assert guide.count("Some Actor") == 2  # the kept block's and the one made again
    with open(str(tmp_path / "iptv" / iptvfiles.KEYS), encoding="utf-8") as f:
        assert len(json.load(f)) == 2  # this export's blocks only: the file does not grow
    # Without the cast, the keys are not needed at all.
    stats = {}
    iptvfiles.export(client, CHANNELS, str(tmp_path), plugin_url, stats=stats)
    assert "read" not in stats


def test_instance_file_never_takes_foreign_instances(tmp_path):
    for i in (1, 2, 3):
        foreign = '<settings><setting id="m3uUrl">http://other/%d</setting></settings>' % i
        (tmp_path / ("instance-settings-%d.xml" % i)).write_text(foreign)
    before = {p: hashlib.md5(open(p, "rb").read()).hexdigest() for p in tmp_path.iterdir()}

    m3u = "special://profile/addon_data/plugin.video.simplego/iptv/channels.m3u"
    path = iptvsimple.instance_file(str(tmp_path), m3u)
    assert os.path.basename(path) == "instance-settings-4.xml"
    new_instance(tmp_path, m3u, m3u.replace("channels.m3u", "epg.xml.gz"))

    # The second run finds and reuses its own instance.
    assert iptvsimple.instance_file(str(tmp_path), m3u) == path
    assert {p: hashlib.md5(open(p, "rb").read()).hexdigest() for p in before} == before


def test_new_instance_settings(tmp_path):
    values = new_instance(tmp_path, "special://a.m3u", "special://b.xml")
    assert values["m3uPath"] == "special://a.m3u"
    assert values["epgPath"] == "special://b.xml"
    assert values["kodi_addon_instance_name"] == "Simple GO"
    assert values["m3uRefreshIntervalMins"] == "60"  # IPTV Simple re-reads the local files hourly


def test_update_instance_writes_only_when_asked_to_create_or_our_files_moved(tmp_path):
    m3u = "special://x/channels.m3u"
    assert not iptvsimple.update_instance(str(tmp_path), m3u, "special://x/epg.xml")  # nothing to update without create
    assert not list(tmp_path.iterdir())
    assert iptvsimple.update_instance(str(tmp_path), m3u, "special://x/epg.xml", create=True)
    assert not iptvsimple.update_instance(str(tmp_path), m3u, "special://x/epg.xml")
    # An instance pointing at another guide file is rewritten in place.
    assert iptvsimple.update_instance(str(tmp_path), m3u, "special://x/epg.xml.gz")
    (path,) = tmp_path.iterdir()
    assert path.name == "instance-settings-1.xml" and "epg.xml.gz" in path.read_text(encoding="utf-8")


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

    class Client:
        epg_stats = {}  # the guide's own count of blocks fetched and kept

        def epg_blocks(self, past_days=1, days_ahead=7, **kw):
            return _blocks((None, None, progs))

    iptvfiles.export(Client(), CHANNELS[:1], str(tmp_path), plugin_url)
    mapping = ET.parse(str(tmp_path / "iptv" / iptvfiles.GENRE_MAP)).getroot()
    ids = {g.text: int(g.get("genreId"), 16) for g in mapping.findall("genre")}
    assert ids["Vígjáték"] == 0x14 and ids["Labdarúgás"] == 0x43 and ids["Hír- és politikai műsorok"] == 0x20
    with gzip.open(str(tmp_path / "iptv" / "epg.xml.gz")) as f:
        prog = ET.parse(f).getroot().find("programme")
    # The broad "Sorozatok" goes last, so IPTV Simple colours this one as a comedy.
    assert [c.text for c in prog.findall("category")] == ["Vígjáték", "Sorozatok"]

    settings = new_instance(tmp_path / "iptvsimple", "special://x/channels.m3u", "special://x/epg.xml.gz")
    assert settings["genresPath"] == "special://x/genres.xml" and settings["useEpgGenreText"] == "true"


def test_channel_category_colours_programmes_without_their_own():
    def cats(channel_genre, *names):
        prog = {"start_time": "2026-10-25T00:00:00Z", "end_time": "2026-10-25T01:00:00Z", "genres": [{"name": n} for n in names]}
        xml = iptvfiles._programme("c", prog, channel_genre)
        return [c.text for c in ET.fromstring(xml).findall("category")]

    assert cats("Gyerekeknek") == ["Gyerekeknek"]  # no category of its own
    assert cats("Gyerekeknek", "Sorozatok") == ["Gyerekeknek", "Sorozatok"]  # only a broad one
    assert cats("Gyerekeknek", "Egyéb", "Ismeretlen") == ["Gyerekeknek", "Ismeretlen", "Egyéb"]
    assert cats("Gyerekeknek", "Sorozatok", "Vígjáték") == ["Vígjáték", "Sorozatok"]  # its own wins
    assert cats(None, "Sorozatok") == ["Sorozatok"]  # a channel of mixed content adds nothing


def test_year_and_age_rating():
    def programme(**extra):
        prog = dict({"start_time": "2026-10-25T00:00:00Z", "end_time": "2026-10-25T01:00:00Z"}, **extra)
        return ET.fromstring(iptvfiles._programme("c", prog))

    p = programme(release_year="1997", show_type="Movie", ratings="16+")
    assert p.find("date").text == "1997" and p.find("rating/value").text == "16"
    # Trakt would take a news programme with a year for a movie: only movies and numbered episodes get it.
    assert programme(release_year="2026", show_type="TVShow").find("date") is None
    assert programme(release_year="1982", show_type="TVShow", season_number=1, episode_number=3).find("date").text == "1982"
    assert programme(ratings="18").find("rating/value").text == "18"
    p = programme(release_year=None, ratings="0-99")  # no year, no age limit
    assert p.find("date") is None and p.find("rating") is None


def test_update_instance_keeps_what_the_user_set_in_iptv_simple(tmp_path):
    m3u, epg = "special://x/channels.m3u", "special://x/epg.xml.gz"
    assert iptvsimple.update_instance(str(tmp_path), m3u, epg, create=True)
    (path,) = tmp_path.iterdir()
    # Changed in IPTV Simple's own settings (Kodi writes them with attributes).
    text = path.read_text(encoding="utf-8")
    interval, enabled = '<setting id="m3uRefreshIntervalMins"', '<setting id="kodi_addon_instance_enabled"'
    text = text.replace(interval + ">60<", interval + ' default="false">15<').replace(enabled + ">true<", enabled + ">false<")
    path.write_text(text, encoding="utf-8")
    assert not iptvsimple.update_instance(str(tmp_path), m3u, epg)  # nothing of ours changed: left alone
    # Our files moved: only those are rewritten, the user's choices stay.
    assert iptvsimple.update_instance(str(tmp_path), m3u, "special://y/epg.xml.gz")
    values = {s.get("id"): s.text for s in ET.parse(str(path)).getroot()}
    assert values["epgPath"] == "special://y/epg.xml.gz" and values["genresPath"] == "special://y/genres.xml"
    assert values["m3uRefreshIntervalMins"] == "15" and values["kodi_addon_instance_enabled"] == "false"


def test_info_pages_give_the_cast_fetched_once(tmp_path):
    pages = {
        ("program", "M1"): {
            "details": {"description": "Kincskeresés."},
            "roles": [
                {"role_name": "Színész", "person_name": "Bud Spencer"},
                {"role_name": "Rendező", "person_name": "Sergio Corbucci"},
                {"role_name": "Producer", "person_name": "Nem kell"},
            ],
        },
        ("series", "S1"): {"details": {}, "roles": [{"role_name": "Színész", "person_name": "Jean-Luc"}]},
    }

    class Client:
        def __init__(self):
            self.asked = []

        def details(self, kind, item_id):
            self.asked.append((kind, item_id))
            return pages[(kind, item_id)]

    client = Client()
    movie = {"program_id": "M1", "show_type": "Movie"}
    episode = {"program_id": "E1", "series_id": "S1", "genres": [{"name": "Sorozatok"}]}
    progs = [movie, episode, dict(episode, program_id="E2")]
    keys = [k for p in progs for k in infopages.keys_of(p)]
    cache = infopages.info_for(client, keys, str(tmp_path))
    # The series page once for both episodes (the plots come with the guide).
    assert sorted(client.asked) == [("program", "M1"), ("series", "S1")]
    assert infopages.programme_credits(movie, cache) == {"actor": ["Bud Spencer"], "director": ["Sergio Corbucci"]}
    assert infopages.programme_credits(episode, cache) == {"actor": ["Jean-Luc"]}

    # Next refresh: nothing new to fetch; what left the guide is dropped from the cache.
    client.asked.clear()
    assert list(infopages.info_for(client, infopages.keys_of(movie), str(tmp_path))) == [("program", "M1")] and client.asked == []

    # The plot from the guide, the cast from the info page.
    times = {"start_time": "2026-10-25T00:00:00Z", "end_time": "2026-10-25T01:00:00Z", "full_description": "Kincskeresés."}
    prog = ET.fromstring(iptvfiles._programme("c", dict(movie, **times), None, infopages.programme_credits(movie, cache)))
    assert prog.find("desc").text == "Kincskeresés."
    assert prog.find("credits/director").text == "Sergio Corbucci" and prog.find("credits/actor").text == "Bud Spencer"


def test_export_reports_progress_and_can_be_cancelled(tmp_path):
    class Client:
        epg_stats = {}  # the guide's own count of blocks fetched and kept

        def epg_blocks(self, progress=None, **kw):
            progress(1, 2)
            progress(2, 2)
            return _blocks((None, None, PROGRAMMES))

    stages = []
    stats = {}
    iptvfiles.export(Client(), CHANNELS, str(tmp_path), plugin_url, progress=lambda *a: stages.append(a), stats=stats)
    assert stages == [("guide", 1, 2), ("guide", 2, 2), ("build", 0, 1), ("build", 1, 1), ("compress",)]
    assert {"guide", "info", "write"} <= set(stats)

    def cancel(stage, *a):
        if stage == "compress":
            raise iptvfiles.Cancelled()

    out = tmp_path / "second"
    with pytest.raises(iptvfiles.Cancelled):
        iptvfiles.export(Client(), CHANNELS, str(out), plugin_url, progress=cancel)
    # No file written: only the blocks' XML made so far is kept, for the next time.
    assert os.listdir(str(out / "iptv")) == [iptvfiles.XML_DIR]


def test_catchup_in_playlist_and_guide(tmp_path):
    channels = [dict(CHANNELS[0], catchup=True), CHANNELS[1]]
    first = dict(PROGRAMMES["1001"][0], content_flags=["ct", "fw"])
    later = dict(first, start_time="2026-10-25T19:00:00Z", end_time="2026-10-25T20:00:00Z", content_flags=["nb"])
    progs = {"1001": [first, later]}

    class Client:
        epg_stats = {}  # the guide's own count of blocks fetched and kept

        def epg_blocks(self, **kw):
            return _blocks((None, None, progs))

    iptvfiles.export(Client(), channels, str(tmp_path), lambda **kw: "plugin://plugin.video.simplego/?" + urlencode(kw))
    m3u = _channel_lines(tmp_path)
    # IPTV Simple's placeholder stays as it is; the radio channel has no archive.
    # Days ignored: IPTV Simple offers just the programmes with a catchup-id.
    assert 'catchup="default" catchup-days="-1"' in m3u[1] and "programme={catchup-id}" in m3u[1]
    # IPTV Simple takes a line with "media=" in it for a recording, not a channel.
    assert "media=" not in m3u[1] and "media-dir=" not in m3u[1] and "media-size=" not in m3u[1]
    assert "catchup" not in m3u[3]
    with gzip.open(str(tmp_path / "iptv" / "epg.xml.gz")) as f:
        prog, no_archive = ET.parse(f).getroot().findall("programme")
    assert no_archive.get("catchup-id") is None  # not in the archive ("ct"): not offered
    param = prog.get("catchup-id")
    assert param == "2026-10-25T17:55:00Z~2026-10-25T18:30:00Z~ct.fw~"  # no age rating
    parsed = guidedata.from_param(param)
    assert parsed["start"] == "2026-10-25T17:55:00Z" and parsed["flags"] == {"ct", "fw"}
    assert parsed["end"] == calendar.timegm((2026, 10, 25, 18, 30, 0))
    assert guidedata.from_param("") is None and guidedata.from_param("x~y~z") is None


def test_update_instance_starts_with_catchup_on_and_leaves_it_to_the_user(tmp_path):
    m3u, epg = "special://x/channels.m3u", "special://x/epg.xml.gz"
    iptvsimple.update_instance(str(tmp_path), m3u, epg, create=True)
    (path,) = tmp_path.iterdir()
    assert '<setting id="catchupEnabled">true</setting>' in path.read_text(encoding="utf-8")
    # Switched off by the user: left so.
    path.write_text(path.read_text(encoding="utf-8").replace('"catchupEnabled">true', '"catchupEnabled">false'))
    assert not iptvsimple.update_instance(str(tmp_path), m3u, epg)
    assert '"catchupEnabled">false' in path.read_text(encoding="utf-8")


def test_favourite_channels_are_a_group_of_their_own(tmp_path):
    channels = [CHANNELS[1], dict(CHANNELS[0], groups=["Kedvencek"])]
    iptvfiles.export(FakeClient(), channels, str(tmp_path), plugin_url)
    m3u = (tmp_path / "iptv" / "channels.m3u").read_text(encoding="utf-8").splitlines()
    # The groups in order up front (then ended), the channels in their own order.
    assert m3u[1:3] == ["#EXTGRP:Simple GO;Kedvencek", "#EXTGRP:"]
    assert 'group-title="Simple GO"' in m3u[3]
    assert 'group-title="Simple GO;Kedvencek;Sport;Hír, info"' in m3u[5]


def test_the_lists_pages_are_fetched_once_and_kept_a_month(tmp_path):
    class Client:
        asked = []

        def details(self, kind, item_id):
            self.asked.append(item_id)
            return {"details": {"description": "Plot of %s " % item_id}}

    client = Client()
    infopages.keep_plot("P1", "Watched back here.", str(tmp_path))  # as it started playing
    keys = [("program", "P1"), ("program", "P2"), ("series", "S1"), ("program", None)]
    # A plot alone wanted: the one kept from the guide will do.
    pages = infopages.pages_for(client, keys, str(tmp_path), full=False)
    assert {key: page["plot"] for key, page in pages.items()} == {
        ("program", "P1"): "Watched back here.",
        ("program", "P2"): "Plot of P2",
        ("series", "S1"): "Plot of S1",
    }
    assert sorted(client.asked) == ["P2", "S1"]
    # The whole page wanted (its type, year...): the one with only a kept plot is fetched, the others not again.
    assert infopages.pages_for(client, keys, str(tmp_path))[("program", "P2")]["type"] == "other"
    assert sorted(client.asked) == ["P1", "P2", "S1"]
    # One not asked for in a month goes.
    path = tmp_path / infopages.PAGE_CACHE
    kept = json.loads(path.read_text(encoding="utf-8"))
    kept["program/P1"]["used"] = time.time() - infopages.PAGE_KEPT - 1
    path.write_text(json.dumps(kept), encoding="utf-8")
    infopages.pages_for(client, [("program", "P2")], str(tmp_path))
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"program/P2", "series/S1"}


def test_the_guide_without_category_colours_has_a_mapping_of_its_own(tmp_path):
    m3u, epg = "special://x/channels.m3u", "special://x/epg.xml.gz"
    assert "<genre " not in iptvfiles.genre_map(colours=False) and "<genre " in iptvfiles.genre_map()
    assert iptvsimple.update_instance(str(tmp_path), m3u, epg, create=True)
    # Switched off: the instance reads the empty mapping instead, so IPTV Simple restarts to read it.
    assert iptvsimple.update_instance(str(tmp_path), m3u, epg, colours=False)
    (path,) = tmp_path.iterdir()
    values = {s.get("id"): s.text for s in ET.parse(str(path)).getroot()}
    assert values["genresPath"] == "special://x/genres-plain.xml" and values["useEpgGenreText"] == "true"
    assert not iptvsimple.update_instance(str(tmp_path), m3u, epg, colours=False)
    assert iptvsimple.update_instance(str(tmp_path), m3u, epg)  # and back


def test_one_request_per_page_gives_the_lists_plot_type_year_and_cast(tmp_path):
    pages = {
        ("program", "M1"): {
            "show_type": "Movie",
            "release_year": 1972,
            "details": {"description": "Plot."},
            "roles": [{"role_name": "Színész", "person_name": "Bud Spencer"}, {"role_name": "Producer", "person_name": "X"}],
        },
        ("series", "S1"): {
            "show_type": "TVShow",
            "details": {"metadata": [{"type": "GENRES", "value": "Vígjáték,Sorozatok"}]},
            "roles": [{"role_name": "Rendező", "person_name": "Rendező Úr"}],
        },
    }

    asked = []

    class Client:
        def details(self, kind, item_id):
            asked.append((kind, item_id))
            return pages[(kind, item_id)]

    made = []
    got = infopages.pages_for(lambda: made.append(1) or Client(), list(pages), str(tmp_path))
    movie = got[("program", "M1")]
    assert (movie["plot"], movie["type"], movie["year"], movie["actor"]) == ("Plot.", "movie", 1972, ["Bud Spencer"])
    assert got[("series", "S1")]["type"] == "series" and got[("series", "S1")]["director"] == ["Rendező Úr"]
    # Asked again: nothing fetched, no client made; the export's own file is not touched.
    asked.clear()
    assert infopages.pages_for(lambda: made.append(1) or Client(), [("program", "M1")], str(tmp_path))
    assert asked == [] and made == [1] and not (tmp_path / infopages.INFO_CACHE).exists()
    # The export takes the roles only.
    assert infopages.programme_credits({"program_id": "M1", "show_type": "Movie"}, got) == {"actor": ["Bud Spencer"]}


def test_an_airings_episode_numbers_come_from_its_info_page(tmp_path):
    class Client:
        def details(self, kind, item_id):
            return {"E1": {"season_number": "2", "episode_number": 5}, "F1": {"show_type": "Movie"}}[item_id]

    assert infopages.episode_numbers(Client(), ["E1", "F1", None], str(tmp_path)) == {"E1": (2, 5)}
