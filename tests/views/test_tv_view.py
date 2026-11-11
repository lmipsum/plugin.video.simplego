"""Kodi TV's switch in the settings: switching on and off, the restart it needs asked for."""

import pytest
from kodiside import call

SETTINGS_OPENED = ("Addon.OpenSettings(plugin.video.simplego)", "builtin")
QUIT = ("Quit", "builtin")
RESTART = ("RestartApp", "builtin")


@pytest.fixture
def restart_questions(kodi, monkeypatch):
    """The restart questions asked, as (message, yes button); tv.ask_restart to ask one."""
    import xbmcgui

    from resources.lib.views import tv

    asked = []

    def yesno(self, heading, message, nolabel="", yeslabel="", **kwargs):
        asked.append((message, yeslabel))
        return kodi.ANSWERS.get("yesno", False)

    monkeypatch.setattr(xbmcgui.Dialog, "yesno", yesno)
    monkeypatch.setattr(tv.kodiutil, "kodi_string", lambda string_id: {13009: "Quit", 13313: "Restart"}.get(string_id, ""))
    return asked, tv.ask_restart


def test_switching_the_tv_menu_on_android_asks_to_quit(kodi, restart_questions):
    asked, ask_restart = restart_questions
    assert ask_restart("Shows after a restart.") is False  # answered no: Kodi goes on
    assert asked[-1] == ("Shows after a restart. Quit now? Then start Kodi again.", "Quit")
    kodi.ANSWERS["yesno"] = True
    assert ask_restart("Shows after a restart.") is True
    assert QUIT in kodi.LOG  # Android cannot restart Kodi: it quits


def test_switching_the_tv_menu_off_android_asks_to_restart(kodi, restart_questions):
    asked, ask_restart = restart_questions
    kodi.CONDITIONS["System.Platform.Android"] = False
    kodi.ANSWERS["yesno"] = True
    assert ask_restart("Shows after a restart.") is True
    assert asked[-1] == ("Shows after a restart. Restart now?", "Restart") and RESTART in kodi.LOG


@pytest.fixture
def views(kodi, monkeypatch):
    from resources.lib.tv import kodipvr
    from resources.lib.views import tv

    p = tv.TvViews(call("?action=tv_toggle", "-1", client=object()))
    p.switched = []
    p.on = (12, 3400, True)  # what kodipvr.switch_on gives: channels, programmes, whether the instance changed
    p.removed = True

    def switch_on(client, progress):
        p.switched.append("on")
        if isinstance(p.on, Exception):
            raise p.on
        return p.on

    def switch_off(update):
        p.switched.append("off")
        return p.removed

    monkeypatch.setattr(kodipvr, "switch_on", switch_on)
    monkeypatch.setattr(kodipvr, "switch_off", switch_off)
    return p


def test_the_toggle_switches_on_or_off_by_the_setting(views, kodi):
    kodi.ANSWERS["yesno"] = [True, False]
    views.do_tv_toggle()
    kodi.SETTINGS["pvr_enabled"] = True
    kodi.ANSWERS["yesno"] = [True, False]
    views.do_tv_toggle()
    assert views.switched == ["on", "off"]


def test_switching_on_is_confirmed_first(views, kodi):
    views.do_tv_on()  # answered no
    assert views.switched == [] and SETTINGS_OPENED not in kodi.LOG


def test_switching_on_a_new_instance_asks_for_the_restart(views, kodi):
    kodi.ANSWERS["yesno"] = [True, True]  # switch on; quit or restart now
    views.do_tv_on()
    assert views.switched == ["on"] and QUIT in kodi.LOG
    assert SETTINGS_OPENED not in kodi.LOG  # Kodi goes: no settings to reopen


def test_switching_on_without_restarting_reopens_the_settings(views, kodi):
    kodi.ANSWERS["yesno"] = [True, False]
    views.do_tv_on()
    assert QUIT not in kodi.LOG and SETTINGS_OPENED in kodi.LOG


def test_switching_on_an_unchanged_instance_needs_no_restart(views, kodi):
    views.on = (12, 3400, False)
    kodi.ANSWERS["yesno"] = [True]
    views.do_tv_on()
    assert (kodi.STRINGS[30144] % (12, 3400), "ok") in kodi.LOG and SETTINGS_OPENED in kodi.LOG


def test_switching_on_without_iptv_simple_says_so(views, kodi):
    views.on = None
    kodi.ANSWERS["yesno"] = [True]
    views.do_tv_on()
    assert (kodi.STRINGS[30031], "ok") in kodi.LOG and SETTINGS_OPENED in kodi.LOG


def test_a_cancelled_switch_on_just_reopens_the_settings(views, kodi):
    from resources.lib.tv import iptvfiles

    views.on = iptvfiles.Cancelled()
    kodi.ANSWERS["yesno"] = [True]
    views.do_tv_on()
    assert [m for m, kind in kodi.LOG if kind == "ok"] == [] and SETTINGS_OPENED in kodi.LOG


def test_switching_off_asks_for_the_restart_when_something_was_removed(views, kodi):
    kodi.ANSWERS["yesno"] = [True, True]
    views.do_tv_off()
    assert views.switched == ["off"] and QUIT in kodi.LOG and SETTINGS_OPENED not in kodi.LOG


def test_switching_off_with_nothing_removed_reopens_the_settings(views, kodi):
    views.removed = False
    kodi.ANSWERS["yesno"] = [True]
    views.do_tv_off()
    assert QUIT not in kodi.LOG and SETTINGS_OPENED in kodi.LOG


def test_the_refresh_button_exports_and_reports_through_its_progress(views, kodi, monkeypatch):
    from resources.lib.tv import exportprogress
    from resources.lib.tv import kodipvr

    closed = []

    class Progress:
        def __init__(self, heading):
            pass

        def close(self, result):
            closed.append(result)

    monkeypatch.setattr(exportprogress, "LateProgressDialog", Progress)
    monkeypatch.setattr(kodipvr, "export", lambda client, progress: (12, 3400))
    views.do_tv_refresh()
    assert closed == [(12, 3400)]
