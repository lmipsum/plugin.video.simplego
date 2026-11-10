"""The mark of a plugin call on its way, which the background export waits for."""

from resources.lib.util import pluginbusy


def test_no_call_on_its_way_means_no_wait(kodi):
    pluginbusy.wait_while_busy()  # returns at once


def test_the_export_waits_until_the_call_is_done(kodi, monkeypatch):
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        pluginbusy.end()

    monkeypatch.setattr(pluginbusy.time, "sleep", sleep)
    pluginbusy.begin()
    pluginbusy.wait_while_busy()
    assert waits == [pluginbusy.WAIT_STEP]


def test_a_failed_calls_stale_mark_is_not_waited_for(kodi, monkeypatch):
    pluginbusy.begin()
    started = pluginbusy.time.time()
    monkeypatch.setattr(pluginbusy.time, "time", lambda: started + pluginbusy.STALE + 1)
    monkeypatch.setattr(pluginbusy.time, "sleep", lambda seconds: (_ for _ in ()).throw(AssertionError("waited")))
    pluginbusy.wait_while_busy()
