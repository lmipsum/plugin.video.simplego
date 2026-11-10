"""Kodi TV: the guide's days, the export's settings fingerprint, switching the TV menu on and off."""

import os

import pytest

from resources.lib import kodiutil
from resources.lib import parental
from resources.lib.tv import exportprogress
from resources.lib.tv import kodipvr


def test_the_guide_covers_kodis_own_guide_days_within_what_the_provider_serves(kodi):
    days = {"epg.pastdaystodisplay": 2, "epg.futuredaystodisplay": 5}
    kodi.JSONRPC["Settings.GetSettingValue"] = lambda params: {"value": days[params["setting"]]}
    assert kodipvr.guide_days() == (2, 5)
    days.update({"epg.pastdaystodisplay": 30, "epg.futuredaystodisplay": 31})
    assert kodipvr.guide_days() == (kodipvr.GUIDE_MAX_PAST, kodipvr.GUIDE_MAX_AHEAD)


def test_without_an_answer_from_kodi_the_guide_takes_its_defaults(kodi):
    assert kodipvr.guide_days() == (1, 3)


def test_a_changed_setting_or_lock_asks_for_a_new_export(lock_settings, kodi):
    kodi.JSONRPC["Settings.GetSettingValue"] = lambda params: {"value": 1}
    before = kodipvr.settings_fingerprint()
    kodi.SETTINGS["info_movie"] = "true"
    assert kodipvr.settings_fingerprint() != before
    before = kodipvr.settings_fingerprint()
    parental.save({"age": 18, "unrated": True, "adult": False})
    assert kodipvr.settings_fingerprint() != before


def test_an_export_already_run_for_the_settings_is_not_asked_for_again(kodi):
    fingerprint = ("a", "b")
    assert kodipvr.wants_export(fingerprint, ("old",))
    kodi.PROPERTIES[kodipvr.EXPORTED_PROPERTY] = repr(fingerprint)  # the TV menu switch exported for these
    assert not kodipvr.wants_export(fingerprint, ("old",))
    assert not kodipvr.wants_export(("old",), ("old",))


def test_switching_the_tv_menu_off_removes_only_ours(kodi):
    import xbmcvfs

    from resources.lib.tv import iptvfiles
    from resources.lib.tv import iptvsimple

    profile = kodiutil.ensure_dir(kodipvr.iptv_profile())
    ours = iptvsimple.instance_file(profile, kodipvr.PVR_M3U)
    with open(ours, "w", encoding="utf-8") as f:
        f.write('<settings><setting id="m3uPath">%s</setting></settings>' % kodipvr.PVR_M3U)
    other = os.path.join(profile, "instance-settings-99.xml")
    with open(other, "w", encoding="utf-8") as f:
        f.write('<settings><setting id="m3uPath">http://other</setting></settings>')
    out = kodiutil.ensure_dir(xbmcvfs.translatePath(kodipvr.PVR_DIR))
    exported = (iptvfiles.PLAYLIST, iptvfiles.GUIDE, iptvfiles.GENRE_MAP, iptvfiles.GENRE_MAP_PLAIN)
    exported += (iptvfiles.STATE, iptvfiles.KEYS)
    for name in exported + ("info.json",):
        open(os.path.join(out, name), "w").close()
    kodi.SETTINGS.update(pvr_enabled=True, pvr_last="yesterday")
    kodipvr.switch_off()
    assert not os.path.exists(ours) and os.path.exists(other)
    assert sorted(os.listdir(out)) == ["info.json"]  # the cast stays: the plugin's lists use it too
    assert kodi.SETTINGS["pvr_enabled"] is False and kodi.SETTINGS["pvr_last"] == ""


def test_a_cancelled_switch_on_leaves_the_tv_menu_off(kodi, monkeypatch):
    from resources.lib.tv import iptvfiles

    monkeypatch.setattr(kodipvr, "install_iptv_simple", lambda: True)
    monkeypatch.setattr(kodipvr, "update_instance", lambda profile, create=False: False)

    def cancelled(client, restart=True, progress=None):
        assert kodi.SETTINGS["pvr_enabled"] is True  # on while it exports: the export is the one for these settings
        raise iptvfiles.Cancelled()

    monkeypatch.setattr(kodipvr, "export", cancelled)
    with pytest.raises(iptvfiles.Cancelled):
        kodipvr.switch_on(object(), None)
    assert kodi.SETTINGS["pvr_enabled"] is False
    monkeypatch.setattr(kodipvr, "install_iptv_simple", lambda: False)
    assert kodipvr.switch_on(object(), None) is None


def test_an_export_counts_for_its_settings_from_its_start(kodi, monkeypatch):
    seen = []

    def running(client, restart, report, pause):
        seen.append(kodi.PROPERTIES.get(kodipvr.EXPORTED_PROPERTY))
        raise RuntimeError("network down")

    monkeypatch.setattr(kodipvr, "_export", running)
    kodi.PROPERTIES[kodipvr.EXPORTED_PROPERTY] = "before"
    with pytest.raises(RuntimeError):
        kodipvr.export(object())
    # While it ran, the service saw these settings as being exported; failed, it may try again.
    assert seen == [repr(kodipvr.settings_fingerprint())]
    assert kodi.PROPERTIES[kodipvr.EXPORTED_PROPERTY] == "before"


def test_the_refresh_dialog_opens_only_for_a_slow_export(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(exportprogress.time, "monotonic", lambda: clock[0])
    progress = exportprogress.LateProgressDialog("Refresh")
    progress("guide", 1, 8)
    assert progress.dialog is None  # done before it would only flash
    clock[0] += exportprogress.SHOW_AFTER
    progress("guide", 2, 8)
    assert progress.dialog is not None
    progress.close((70, 100))
