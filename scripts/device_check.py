#!/usr/bin/env python3
"""Check the installed add-on on an Android TV device: play, switch, stop, and read Kodi's log.

    python scripts/device_check.py --device <device-ip>:5555 [--background]

Needs adb connected to the device, Kodi with the add-on logged in and debug logging on, and
"Allow remote control from applications on this system" (Kodi's JSON-RPC, reached through an adb
port forward). It wakes the device, brings Kodi to the front, opens the channel list, plays the
first channel, switches to the second, (with --background: leaves Kodi for the home screen and comes
back,) stops, then reads the log lines written meanwhile. Exits 1 if a check failed.
"""

import argparse
import json
import re
import socket
import subprocess
import sys
import time

PACKAGE = "org.xbmc.kodi"
ACTIVITY = PACKAGE + "/.Splash"
LOG = "/sdcard/Android/data/%s/files/.kodi/temp/kodi.log" % PACKAGE
ADDON = "plugin.video.simplego"
CHANNELS = "plugin://%s/?action=channels" % ADDON
JSONRPC_PORT = 9090
LOCAL_PORT = 19090
# Seconds Kodi may take to answer once in front, a stream to show its picture, a list to settle after a stop.
READY_TIMEOUT = 30
START_TIMEOUT = 20
SETTLE = 6
# Seconds a channel plays before the next step, and Kodi stays behind the home screen with --background.
PLAY_FOR = 10
AWAY_FOR = 10
# A plugin call slower than this (seconds) is reported.
SLOW_CALL = 5.0
# Two full channel lists this close (seconds) after a stop: Kodi showed each channel twice.
DOUBLE_LIST = 3.0

STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})")
OURS = "[%s]" % ADDON
DONE = re.compile(r"\] (\w+): done in ([\d.]+)s")
SECRET = re.compile(r"((?:token|code|password)=)[^&\s\"']+", re.I)


class Adb:
    """adb commands for one device."""

    def __init__(self, serial):
        self.serial = serial

    def run(self, *args):
        """Run an adb command; return its output."""
        found = subprocess.run(["adb", "-s", self.serial, *args], capture_output=True, text=True, timeout=60, check=True)
        return found.stdout

    def shell(self, command):
        return self.run("shell", command)


class JsonRpc:
    """Kodi's JSON-RPC over its TCP port: calls by id, notifications kept for wait_for."""

    def __init__(self, host, port):
        self._sock = socket.create_connection((host, port), timeout=READY_TIMEOUT)
        self._buffer = ""
        self._next_id = 0
        self.notifications = []

    def call(self, method, params=None, timeout=READY_TIMEOUT):
        """Return a method's result; raise RuntimeError with its error."""
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            request["params"] = params
        self._sock.sendall(json.dumps(request).encode("utf-8"))
        message = self._read_until(lambda m: m.get("id") == self._next_id, timeout)
        if "error" in message:
            raise RuntimeError("%s: %s" % (method, message["error"]))
        return message.get("result")

    def wait_for(self, method, timeout):
        """Return the first notification of this method from now on; None if none came in time."""
        del self.notifications[:]
        try:
            return self._read_until(lambda m: m.get("method") == method, timeout)
        except socket.timeout:
            return None

    def _read_until(self, wanted, timeout):
        deadline = time.time() + timeout
        while True:
            messages, self._buffer = split_messages(self._buffer)
            for message in messages:
                if wanted(message):
                    return message
                self.notifications.append(message)
            left = deadline - time.time()
            if left <= 0:
                raise socket.timeout("no answer in %d s" % timeout)
            self._sock.settimeout(left)
            data = self._sock.recv(65536)
            if not data:
                raise ConnectionError("Kodi closed the connection")
            self._buffer += data.decode("utf-8", "replace")


def split_messages(text):
    """Return (the complete JSON objects at the front of text, the rest): Kodi sends them back to back."""
    decoder = json.JSONDecoder()
    messages = []
    while True:
        text = text.lstrip()
        try:
            message, end = decoder.raw_decode(text)
        except ValueError:
            return messages, text
        messages.append(message)
        text = text[end:]


def analyse(lines, stops):
    """Return the failures and notes found in the log lines written during the check.

    :param stops: the times (epoch seconds) the check stopped playback
    :return: (failures, notes), each a list of strings
    """
    failures, notes, slowest, full_lists = [], [], {}, []
    for line in lines:
        stamp = _stamp(line)
        if OURS in line and (" error <" in line or " warning <" in line):
            failures.append("add-on %s" % _clean(line))
        elif 'File "' in line and "/addons/%s/" % ADDON in line:
            failures.append("Python error in %s" % _clean(line))
        done = DONE.search(line) if OURS in line else None
        if done:
            action, seconds = done.group(1), float(done.group(2))
            slowest[action] = max(slowest.get(action, 0), seconds)
            if action == "channels" and "from the service" in line and stamp:
                full_lists.append(stamp)
    for stop in stops:
        after = [t for t in full_lists if 0 <= t - stop <= SETTLE + DOUBLE_LIST]
        if any(b - a <= DOUBLE_LIST for a, b in zip(after, after[1:])):
            clock = time.strftime("%H:%M:%S", time.localtime(stop))
            failures.append("two channel lists made at once after the stop at %s" % clock)
    for action, seconds in sorted(slowest.items()):
        (failures if seconds > SLOW_CALL else notes).append("%s: slowest %.2f s" % (action, seconds))
    return failures, notes


def _stamp(line):
    found = STAMP.match(line.lstrip("\ufeff"))
    if not found:
        return None
    return time.mktime(time.strptime(found.group(1)[:19], "%Y-%m-%d %H:%M:%S")) + float(found.group(1)[19:])


def _clean(line):
    """A log line without its time and thread, its secrets masked, cut short."""
    return SECRET.sub(r"\g<1>…", line.split("> ", 1)[-1].strip())[:200]


class DeviceCheck:
    """The check's steps on one device; each records what it found in `failures` and `notes`."""

    def __init__(self, adb):
        self.adb = adb
        self.failures, self.notes, self.stops = [], [], []
        self.kodi = None

    def run(self, background=False):
        self.adb.shell("input keyevent KEYCODE_WAKEUP")
        self.adb.shell("am start -n %s" % ACTIVITY)
        self.adb.run("forward", "tcp:%d" % LOCAL_PORT, "tcp:%d" % JSONRPC_PORT)
        self.kodi = self._connect()
        first_line = int(self.adb.shell("wc -l < %s" % LOG).split()[0]) + 1
        details = self.kodi.call("Addons.GetAddonDetails", {"addonid": ADDON, "properties": ["version", "enabled"]})
        self.notes.append("%s %s" % (ADDON, details["addon"]["version"]))
        channels = self._channel_list()
        if len(channels) >= 2:
            self._play(channels[0], "start")
            time.sleep(PLAY_FOR)
            self._play(channels[1], "switch")
            time.sleep(PLAY_FOR)
            if background:
                self._leave_and_return()
            self._stop()
        lines = self.adb.shell("tail -n +%d %s" % (first_line, LOG)).splitlines()
        failures, notes = analyse(lines, self.stops)
        self.failures += failures
        self.notes += notes
        return not self.failures

    def _connect(self):
        deadline = time.time() + READY_TIMEOUT
        while True:
            try:
                kodi = JsonRpc("127.0.0.1", LOCAL_PORT)
                kodi.call("JSONRPC.Ping", timeout=5)
                return kodi
            except (OSError, socket.timeout) as e:
                if time.time() > deadline:
                    raise SystemExit("Kodi's JSON-RPC does not answer: is remote control from this system allowed?") from e
                time.sleep(1)

    def _channel_list(self):
        """Return the channel list's playable rows, then open it in Kodi (so a stop returns to it).

        One after the other: of two lists asked for at once the add-on makes one (see views.channels).
        """
        started = time.time()
        files = self.kodi.call("Files.GetDirectory", {"directory": CHANNELS, "media": "files"}, timeout=60).get("files") or []
        self.notes.append("channel list: %d rows in %.1f s" % (len(files), time.time() - started))
        self.kodi.call("GUI.ActivateWindow", {"window": "videos", "parameters": [CHANNELS, "return"]})
        time.sleep(SETTLE)
        playable = [f["file"] for f in files if "action=play" in f["file"]]
        if len(set(playable)) != len(playable):
            self.failures.append("the channel list has the same channel twice")
        if len(playable) < 2:
            self.failures.append("the channel list has %d playable rows" % len(playable))
        return playable

    def _play(self, path, step):
        started = time.time()
        self.kodi.call("Player.Open", {"item": {"file": path}})
        if self.kodi.wait_for("Player.OnAVStart", START_TIMEOUT) is None:
            self.failures.append("%s: no picture within %d s" % (step, START_TIMEOUT))
        else:
            self.notes.append("%s: picture in %.1f s" % (step, time.time() - started))

    def _leave_and_return(self):
        """Go to the home screen and back; Kodi or the add-on must be playing again."""
        self.adb.shell("input keyevent KEYCODE_HOME")
        time.sleep(AWAY_FOR)
        self.adb.shell("am start -n %s" % ACTIVITY)
        deadline = time.time() + START_TIMEOUT
        while time.time() < deadline:
            if self.kodi.call("Player.GetActivePlayers"):
                self.notes.append("back from the home screen: playing")
                return
            time.sleep(1)
        self.failures.append("back from the home screen: nothing plays")

    def _stop(self):
        players = self.kodi.call("Player.GetActivePlayers") or []
        for player in players:
            self.kodi.call("Player.Stop", {"playerid": player["playerid"]})
        self.stops.append(time.time())
        time.sleep(SETTLE)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--device", required=True, help="the adb serial, e.g. <device-ip>:5555")
    parser.add_argument("--background", action="store_true", help="also leave Kodi for the home screen and come back")
    args = parser.parse_args()
    check = DeviceCheck(Adb(args.device))
    ok = check.run(background=args.background)
    for note in check.notes:
        print("  " + note)
    for failure in check.failures:
        print("FAIL " + failure)
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
