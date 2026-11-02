"""The background service's export schedule."""

import time

from resources.lib import kodiutil


def test_a_change_made_elsewhere_exports_once_the_settings_dialog_is_closed(kodi, monkeypatch):
    from resources.lib.service import background

    started = []
    monkeypatch.setattr(background, "_export", lambda progress: started.append(type(progress).__name__))
    kodi.SETTINGS.update(pvr_enabled=True, pvr_interval=0, pvr_last_at=str(int(time.time())))
    schedule = background.ExportSchedule()
    monitor = background._Monitor()
    kodi.PROPERTIES[kodiutil.EXPORT_REQUEST] = "1"  # the favourites changed, say
    kodi.CONDITIONS["Window.IsActive(addonsettings)"] = True
    schedule.look(monitor)
    schedule.export_if_wanted()
    assert started == []  # not while the settings dialog is open
    kodi.CONDITIONS.clear()
    monitor.changed_at -= background.SETTINGS_DEBOUNCE + 1
    schedule.look(monitor)
    schedule.export_if_wanted()
    schedule.exporting.join()
    assert started == ["BackgroundProgress"]  # asked for by the user: shown


def test_the_schedule_exports_silently_and_a_login_change_visibly(kodi, monkeypatch):
    from resources.lib.service import background

    started, forgotten = [], []
    monkeypatch.setattr(background, "_export", lambda progress: started.append(type(progress).__name__))
    monkeypatch.setattr(background, "_show_login_state", lambda: None)
    monkeypatch.setattr(background.clientfactory, "forget_shared_client", lambda: forgotten.append(True))
    # Refreshed every hour, last two hours ago: due.
    kodi.SETTINGS.update(pvr_enabled=True, pvr_interval=1, pvr_last_at=str(int(time.time()) - 7200))
    schedule = background.ExportSchedule()
    monitor = background._Monitor()
    schedule.look(monitor)
    schedule.export_if_wanted()
    assert started == []  # not in Kodi's first FIRST_DELAY: it would slow the start
    schedule.last -= background.FIRST_DELAY
    schedule.look(monitor)
    schedule.export_if_wanted()
    schedule.exporting.join()
    assert started == ["Progress"]  # the clock's: no progress shown
    schedule.look(monitor)
    schedule.export_if_wanted()
    assert started == ["Progress"]  # just done: not due again
    # Logged in or out: the guide switches to the other channel list, and the user sees it.
    kodi.PROPERTIES[kodiutil.LOGIN_CHANGED] = "1"
    schedule.look(monitor)
    schedule.export_if_wanted()
    schedule.exporting.join()
    assert started == ["Progress", "BackgroundProgress"] and forgotten == [True]
    assert kodiutil.LOGIN_CHANGED not in kodi.PROPERTIES


def test_without_kodi_tv_set_up_nothing_is_exported(kodi, monkeypatch):
    from resources.lib.service import background

    started = []
    monkeypatch.setattr(background, "_export", lambda progress: started.append(progress))
    kodi.SETTINGS.update(pvr_enabled=False, pvr_interval=1, pvr_last_at="0")
    schedule = background.ExportSchedule()
    kodi.PROPERTIES[kodiutil.LOGIN_CHANGED] = "1"
    monkeypatch.setattr(background.threading, "Thread", lambda **kwargs: type("T", (), {"start": lambda self: None})())
    schedule.look(background._Monitor())
    schedule.export_if_wanted()
    assert started == []


def test_the_service_rounds_are_summed_up_once_an_hour(kodi):
    from resources.lib.service import background

    rounds = background.RoundTimes(now=1000.0)
    rounds.add(0.002, busy=False, now=1001.0)
    rounds.add(0.004, busy=False, now=1002.0)
    rounds.add(0.010, busy=True, now=1003.0)
    assert not any("service rounds" in m for m, _ in kodi.LOG)
    rounds.add(0.006, busy=False, now=1000.0 + background.RoundTimes.EVERY)
    (line,) = [m for m, _ in kodi.LOG if "service rounds" in m]
    assert "idle 3, mean 4.0 ms, max 6.0 ms; with a stream 1, mean 10.0 ms, max 10.0 ms" in line
    assert rounds.summary() == "none"  # a new hour


def test_getting_ready_ahead_asks_the_client(kodi, monkeypatch):
    import types

    from resources.lib.service import background

    asked = []
    client = types.SimpleNamespace(get_ready=asked.append)
    monkeypatch.setattr(background.clientfactory, "shared_client", lambda: client)
    background._get_ready()
    assert asked == [background.READY_AHEAD]
    assert not [m for m, level in kodi.LOG if "failed" in str(m)]  # renewed, not given up on
