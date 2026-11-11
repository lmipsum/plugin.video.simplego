"""IPTV Simple's instance for the export: found among others, written new, updated only where our files moved."""

import hashlib
import os
import xml.etree.ElementTree as ET

from resources.lib.tv import iptvsimple

M3U, EPG = "special://x/channels.m3u", "special://x/epg.xml.gz"


def _values(path):
    """Return an instance file's settings, by id."""
    return {s.get("id"): s.text for s in ET.parse(str(path)).getroot()}


def new_instance(folder, m3u, epg):
    """Return the settings of a new instance written for these files, by id."""
    os.makedirs(str(folder), exist_ok=True)
    assert iptvsimple.update_instance(str(folder), m3u, epg, create=True)
    return _values(iptvsimple.instance_file(str(folder), m3u))


def _only_instance(tmp_path):
    """Write a new instance for M3U and EPG; its file."""
    assert iptvsimple.update_instance(str(tmp_path), M3U, EPG, create=True)
    (path,) = tmp_path.iterdir()
    return path


def test_instance_file_never_takes_foreign_instances(tmp_path):
    for i in (1, 2, 3):
        foreign = '<settings><setting id="m3uUrl">http://other/%d</setting></settings>' % i
        (tmp_path / ("instance-settings-%d.xml" % i)).write_text(foreign)
    before = {p: hashlib.md5(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}

    m3u = "special://profile/addon_data/plugin.video.simplego/iptv/channels.m3u"
    path = iptvsimple.instance_file(str(tmp_path), m3u)
    assert os.path.basename(path) == "instance-settings-4.xml"
    new_instance(tmp_path, m3u, m3u.replace("channels.m3u", "epg.xml.gz"))

    # The second run finds and reuses its own instance.
    assert iptvsimple.instance_file(str(tmp_path), m3u) == path
    assert {p: hashlib.md5(p.read_bytes()).hexdigest() for p in before} == before


def test_new_instance_settings(tmp_path):
    values = new_instance(tmp_path, "special://a.m3u", "special://b.xml")
    assert values["m3uPath"] == "special://a.m3u"
    assert values["epgPath"] == "special://b.xml"
    assert values["kodi_addon_instance_name"] == "Simple GO"
    assert values["m3uRefreshIntervalMins"] == "60"  # IPTV Simple re-reads the local files hourly


def test_a_new_instance_reads_the_genre_mapping_beside_the_guide(tmp_path):
    settings = new_instance(tmp_path, M3U, EPG)
    assert settings["genresPath"] == "special://x/genres.xml" and settings["useEpgGenreText"] == "true"


def test_update_instance_writes_nothing_unless_asked_to_create(tmp_path):
    assert not iptvsimple.update_instance(str(tmp_path), M3U, "special://x/epg.xml")
    assert not list(tmp_path.iterdir())


def test_update_instance_leaves_an_instance_for_our_files_alone(tmp_path):
    assert iptvsimple.update_instance(str(tmp_path), M3U, "special://x/epg.xml", create=True)
    assert not iptvsimple.update_instance(str(tmp_path), M3U, "special://x/epg.xml")


def test_update_instance_rewrites_an_instance_pointing_at_another_guide_file_in_place(tmp_path):
    assert iptvsimple.update_instance(str(tmp_path), M3U, "special://x/epg.xml", create=True)
    assert iptvsimple.update_instance(str(tmp_path), M3U, EPG)
    (path,) = tmp_path.iterdir()
    assert path.name == "instance-settings-1.xml" and "epg.xml.gz" in path.read_text(encoding="utf-8")


def _set_by_user(tmp_path):
    """An instance whose refresh interval and enabling the user changed in IPTV Simple's own settings; its file."""
    path = _only_instance(tmp_path)
    # Kodi writes them with attributes.
    text = path.read_text(encoding="utf-8")
    interval, enabled = '<setting id="m3uRefreshIntervalMins"', '<setting id="kodi_addon_instance_enabled"'
    text = text.replace(interval + ">60<", interval + ' default="false">15<').replace(enabled + ">true<", enabled + ">false<")
    path.write_text(text, encoding="utf-8")
    return path


def test_update_instance_leaves_what_the_user_set_alone_when_nothing_of_ours_changed(tmp_path):
    _set_by_user(tmp_path)
    assert not iptvsimple.update_instance(str(tmp_path), M3U, EPG)


def test_update_instance_keeps_what_the_user_set_when_our_files_moved(tmp_path):
    path = _set_by_user(tmp_path)
    assert iptvsimple.update_instance(str(tmp_path), M3U, "special://y/epg.xml.gz")
    values = _values(path)
    assert values["epgPath"] == "special://y/epg.xml.gz" and values["genresPath"] == "special://y/genres.xml"
    assert values["m3uRefreshIntervalMins"] == "15" and values["kodi_addon_instance_enabled"] == "false"


def test_update_instance_starts_with_catchup_on(tmp_path):
    path = _only_instance(tmp_path)
    assert '<setting id="catchupEnabled">true</setting>' in path.read_text(encoding="utf-8")


def test_update_instance_leaves_catchup_switched_off_by_the_user(tmp_path):
    path = _only_instance(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace('"catchupEnabled">true', '"catchupEnabled">false'))
    assert not iptvsimple.update_instance(str(tmp_path), M3U, EPG)
    assert '"catchupEnabled">false' in path.read_text(encoding="utf-8")


def test_without_category_colours_the_instance_reads_the_plain_mapping(tmp_path):
    path = _only_instance(tmp_path)
    # Switched off: IPTV Simple restarts to read the other mapping.
    assert iptvsimple.update_instance(str(tmp_path), M3U, EPG, colours=False)
    values = _values(path)
    assert values["genresPath"] == "special://x/genres-plain.xml" and values["useEpgGenreText"] == "true"
    assert not iptvsimple.update_instance(str(tmp_path), M3U, EPG, colours=False)


def test_category_colours_switched_on_again_rewrite_the_instance(tmp_path):
    _only_instance(tmp_path)
    iptvsimple.update_instance(str(tmp_path), M3U, EPG, colours=False)
    assert iptvsimple.update_instance(str(tmp_path), M3U, EPG)
