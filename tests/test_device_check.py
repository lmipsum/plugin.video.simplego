"""The device check's own logic: Kodi's JSON-RPC stream split into messages, and its log read for problems."""

import time

import device_check


def line(clock, level, text):
    return "2026-11-11 %s T:1 %7s <general>: %s" % (clock, level, text)


def at(clock):
    return time.mktime(time.strptime("2026-11-11 " + clock[:8], "%Y-%m-%d %H:%M:%S")) + float(clock[8:])


def test_back_to_back_messages_are_split_and_a_partial_one_is_kept():
    messages, rest = device_check.split_messages('{"id": 1} {"method": "Player.OnAVStart"}{"id": 2, "res')
    assert messages == [{"id": 1}, {"method": "Player.OnAVStart"}]
    assert rest == '{"id": 2, "res'


def test_two_full_channel_lists_right_after_a_stop_fail():
    done = "[plugin.video.simplego] channels: done in 2.80s (start 0.7s, from the service 0.8s, items 1.3s)"
    lines = [line("06:32:17.578", "debug", done), line("06:32:17.710", "debug", done)]
    failures, _ = device_check.analyse(lines, stops=[at("06:32:13.000")])
    assert any("two channel lists" in f for f in failures)


def test_one_full_list_and_ended_extra_requests_pass():
    lines = [
        line("06:45:09.842", "debug", "[plugin.video.simplego] channel list asked for again: this one ends"),
        line("06:45:09.843", "debug", "[plugin.video.simplego] channels: done in 0.83s (start 0.77s, imports 0.70s)"),
        line("06:45:11.220", "debug", "[plugin.video.simplego] channels: done in 2.23s (start 0.79s, from the service 0.69s)"),
    ]
    failures, notes = device_check.analyse(lines, stops=[at("06:45:08.465")])
    assert failures == [] and notes == ["channels: slowest 2.23 s"]


def test_a_slow_call_fails_and_the_slowest_of_each_action_is_noted():
    lines = [
        line("06:54:04.531", "debug", "[plugin.video.simplego] root: done in 1.20s (start 0.3s)"),
        line("06:54:15.051", "debug", "[plugin.video.simplego] root: done in %.2fs (start 6.2s)" % (device_check.SLOW_CALL + 1)),
    ]
    failures, notes = device_check.analyse(lines, stops=[])
    assert failures == ["root: slowest %.2f s" % (device_check.SLOW_CALL + 1)] and notes == []


def test_the_add_ons_warnings_and_python_errors_fail_but_other_add_ons_do_not():
    lines = [
        line("07:00:00.000", "warning", "[plugin.video.simplego] beacon failed: login_token=abc&x=1"),
        line("07:00:01.000", "error", "EXCEPTION Thrown (PythonToCppException)"),
        '      File "/storage/.kodi/addons/script.simkl/resources/lib/engine.py", line 47, in _detect_item',
        '      File "/storage/.kodi/addons/plugin.video.simplego/resources/lib/plugin.py", line 9, in run',
    ]
    failures, _ = device_check.analyse(lines, stops=[])
    assert len(failures) == 2
    assert "abc" not in failures[0]  # its secrets masked
    assert "plugin.py" in failures[1]
