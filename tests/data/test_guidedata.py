import pytest

from resources.lib.data import guidedata


def test_channel_colour():
    assert guidedata.channel_colour({"genres": ["Közszolgálati", "Sport"]}) == "FFED0E28"
    assert guidedata.channel_colour({"genres": ["Gyerekeknek"]}) == "FF17DBC2"
    assert guidedata.channel_colour({"genres": ["Közszolgálati", "Helyi TV"]}) is None


def test_programme_type():
    assert guidedata.kind({"show_type": "Movie"}) == "movie"
    assert guidedata.kind({"show_type": "TVShow", "series_id": "s", "genres": [{"name": "Sorozatok"}]}) == "series"
    # News have a series id too, but are not series.
    news = {"show_type": "TVShow", "series_id": "s", "genres": [{"name": "Hír- és politikai műsorok"}]}
    assert guidedata.kind(news) == "other"


def test_rating_ages_and_the_programme_param():
    ratings = ("18+", "18", "16+", "12", "0-99", "", None, "?")
    assert [guidedata.rating_age(r) for r in ratings] == [guidedata.ADULT_AGE, 18, 16, 12, 0, None, None, None]
    p = {"start_time": "2026-10-26T22:00:00Z", "end_time": "2026-10-26T23:15:00Z", "content_flags": ["ct"], "ratings": "18+"}
    param = guidedata.param(p)
    assert param.endswith("~ct~%d" % guidedata.ADULT_AGE) and "+" not in param  # it travels in a URL unencoded
    assert guidedata.from_param(param)["age"] == guidedata.ADULT_AGE
    assert guidedata.from_param(guidedata.param(dict(p, ratings="")))["age"] is None
    assert "age" not in guidedata.from_param("2026-10-26T22:00:00Z~2026-10-26T23:15:00Z~ct")  # no age given


def test_programme_param_unknown_age():
    p = guidedata.from_param("2026-10-26T12:15:00Z~2026-10-26T14:20:00Z~ct~?")
    assert "age" not in p and p["flags"] == {"ct"}
    assert guidedata.from_param("2026-10-26T12:15:00Z~2026-10-26T14:20:00Z~ct~6")["age"] == 6


def test_kodi_resume():
    param = "2026-10-26T12:15:00Z~2026-10-26T14:20:00Z~ct~6~kodi"
    resumed = guidedata.kodi_resume(param, ["plugin://x/", "1", "?a", "resume:true"])
    assert guidedata.from_param(resumed)["resume"] is True
    assert guidedata.from_param(guidedata.kodi_resume(param, ["plugin://x/", "1", "?a", "resume:false"]))["resume"] is False
    assert guidedata.from_param(guidedata.kodi_resume(param, ["plugin://x/", "1", "?a"]))["resume"] is False
    plain = "2026-10-26T12:15:00Z~2026-10-26T14:20:00Z~ct~6"
    assert guidedata.kodi_resume(plain, ["plugin://x/", "1", "?a", "resume:true"]) == plain
    assert "resume" not in guidedata.from_param(plain)


def test_resumed():
    assert guidedata.from_param(guidedata.resumed("2026-10-26T22:00:00Z~2026-10-26T23:15:00Z~ct~16"))["resume"] is True
    plain = guidedata.from_param(guidedata.resumed("2026-10-26T22:00:00Z~2026-10-26T23:15:00Z~ct"))
    assert plain["resume"] is True and "age" not in plain  # looked up in the guide
    asked = "2026-10-26T22:00:00Z~2026-10-26T23:15:00Z~ct~?~start"
    assert guidedata.from_param(guidedata.resumed(asked))["resume"] is True


def test_watched_back_and_restarted_by_the_guide_flags():
    assert guidedata.watchable_back({"content_flags": ["ct", "rn"]}) and not guidedata.restartable({"content_flags": ["rn"]})
    assert not guidedata.watchable_back({"content_flags": None}) and guidedata.restartable({"content_flags": None})
    assert guidedata.restartable({"content_flags": ["ct"]})


@pytest.mark.parametrize("text", ["", "x~y~z"])
def test_a_text_that_is_no_programme_param_reads_as_none(text):
    assert guidedata.from_param(text) is None
