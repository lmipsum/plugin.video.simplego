import json

from resources.lib import resolveditem
from resources.lib.data import guidedata
from resources.lib.stream import playitem

STREAM = {"type": "dash", "user_agent": "Mozilla/5.0 (X)", "server_certificate": "CERT"}


def test_spec_kodi21():
    spec = playitem.spec(STREAM, "http://127.0.0.1:1/manifest", "http://127.0.0.1:1/license", 21)
    assert spec["path"] == "http://127.0.0.1:1/manifest" and spec["mimetype"] == "application/dash+xml"
    props = spec["properties"]
    assert props["inputstream"] == "inputstream.adaptive"
    assert props["inputstream.adaptive.license_key"] == "http://127.0.0.1:1/license|Content-Type=text%2Fplain|R{SSM}|"
    assert props["inputstream.adaptive.server_certificate"] == "CERT"
    assert props["inputstream.adaptive.stream_headers"] == "User-Agent=Mozilla/5.0%20%28X%29"
    assert "inputstream.adaptive.manifest_type" not in props
    json.dumps(spec)  # travels from the service to the plugin as JSON


def test_spec_kodi22_uses_drm_json():
    props = playitem.spec(STREAM, "m", "l", 22)["properties"]
    drm = json.loads(props["inputstream.adaptive.drm"])["com.widevine.alpha"]["license"]
    assert drm == {"server_url": "l", "req_headers": "Content-Type=text%2Fplain", "server_certificate": "CERT"}
    assert "inputstream.adaptive.license_key" not in props


def test_live_starts_the_live_delay_behind_the_edge_in_each_kodis_words():
    from resources.lib.stream import dash

    assert playitem.spec(STREAM, "m", "l", 21)["properties"]["inputstream.adaptive.live_delay"] == str(dash.LIVE_DELAY)
    config = playitem.spec(STREAM, "m", "l", 22)["properties"]["inputstream.adaptive.manifest_config"]
    assert json.loads(config) == {"live_delay": dash.LIVE_DELAY}
    # From the programme's beginning: the start of the window, not the edge.
    restart = playitem.spec(dict(STREAM, from_start=True), "m", "l", 21)["properties"]
    assert restart["inputstream.adaptive.play_timeshift_buffer"] == "true" and "inputstream.adaptive.live_delay" not in restart
    # The window kept where the programme allows no rewinding still holds the start point.
    assert dash.NO_TIMESHIFT_WINDOW > dash.LIVE_DELAY >= 16


def test_a_programme_watched_back_carries_its_guide_details(kodi):
    programme = {
        "description": "Show",
        "episode_name": "Pilot",
        "full_description": " Plot ",
        "genres": [{"name": "Vígjáték"}, {"name": "Sorozatok"}],
        "show_type": "TVShow",
        "series_id": "s",
        "release_year": "1997",
        "season_number": "2",
        "episode_number": 5,
        "program_id": "ABC",
    }
    stream = dict(STREAM, details=guidedata.details(programme))
    spec = playitem.spec(stream, "m", "l", 21)
    json.dumps(spec)
    li = resolveditem.list_item(spec)
    tag = li.getVideoInfoTag()
    assert (tag["TvShowTitle"], tag["Title"], tag["Plot"]) == ("Show", "Pilot", "Plot")
    assert (tag["Year"], tag["Season"], tag["Episode"], tag["MediaType"]) == (1997, 2, 5, "episode")
    assert tag["Genres"] == ["Vígjáték", "Sorozatok"]
    assert li.art["thumb"].endswith("/program/abc/16x9/keyartmedium.jpg")
    # Not the provider's series, but with an episode: an episode all the same; without one, a video.
    cartoon = dict(programme, genres=[{"name": "Rajzfilm"}])
    for details, media in ((cartoon, "episode"), (dict(cartoon, episode_name="", season_number=None), "video")):
        item = resolveditem.list_item(playitem.spec(dict(STREAM, details=guidedata.details(details)), "m", "l", 21))
        assert item.getVideoInfoTag()["MediaType"] == media


def test_only_movies_and_numbered_episodes_are_played_with_their_year():
    """Trakt and Simkl take a played item with a year but no season and episode for a movie."""
    news = {"description": "Híradó", "show_type": "TVShow", "release_year": "2026"}
    assert "year" not in guidedata.details(news)
    assert "year" not in guidedata.details(dict(news, episode_name="Esti kiadás"))
    assert guidedata.details(dict(news, season_number=1, episode_number=3))["year"] == 2026
    assert guidedata.details({"description": "Film", "show_type": "Movie", "release_year": "1972"})["year"] == 1972


def test_live_carries_no_details(kodi):
    li = resolveditem.list_item(playitem.spec(dict(STREAM, details=None), "m", "l", 21))
    assert "tag" not in li.__dict__


def test_the_info_over_playback_shows_the_logo_live_and_the_16x9_picture_watched_back(kodi):
    # Live: the logo as poster, over the row's 2:3 one (Kodi adds this art to the row's).
    li = resolveditem.list_item(playitem.spec(dict(STREAM, logo="logo.png"), "m", "l", 21))
    assert li.art == {"icon": "logo.png", "poster": "logo.png"}
    # Watched back: the programme's 16:9 picture as poster, which the playback info shows.
    details = guidedata.details({"description": "Show", "program_id": "ABC"})
    li = resolveditem.list_item(playitem.spec(dict(STREAM, logo="logo.png", details=details), "m", "l", 21))
    assert li.art["poster"] == li.art["thumb"] and li.art["icon"] == "logo.png"
