"""The state file shared by clients: their saves merged, its lock across separate interpreters.

Kodi runs the service and each plugin run in interpreters of their own (on Android in one OS
process), so a lock in Python's memory does not keep them apart; the lock's tests run real
separate processes.
"""

import json
import os
import subprocess
import sys
import time

from resources.lib.provider import core
from resources.lib.provider import statefile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# One client of the shared state: waits for a common start, then asks for the access
# token. The renewal is a stand-in that rotates the refresh token, as the login server
# does, and logs which refresh token it was given.
WORKER = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
from resources.lib import provider

profile, start, log = sys.argv[2], float(sys.argv[3]), sys.argv[4]
client = provider.Client(profile)

def renew():
    used = client.state["refresh_token"]
    with open(log, "a") as f:
        f.write(used + "\n")
    time.sleep(0.5)  # the renewal's redirects
    client.state.update(refresh_token=used + "+", access_token="a-" + used, access_expires=time.time() + 3600)
    client.state.save()

client.auth._renew = renew
time.sleep(max(0, start - time.time()))
print(client.auth.valid_access_token())
"""


def _run_clients(tmp_path, n):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "session.json").write_text(json.dumps({"refresh_token": "r0", "access_token": "old", "access_expires": 0}))
    worker = tmp_path / "worker.py"
    worker.write_text(WORKER)
    log = tmp_path / "renewals.log"
    start = time.time() + 1.5  # after every interpreter has started
    procs = [
        subprocess.Popen(
            [sys.executable, str(worker), ROOT, str(profile), str(start), str(log)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(n)
    ]
    outputs = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
        outputs.append(out.strip())
    used = log.read_text().split()
    return used, outputs, json.loads((profile / "session.json").read_text())


def test_clients_in_separate_interpreters_renew_the_token_once(tmp_path):
    used, tokens, state = _run_clients(tmp_path, 3)
    # One renewal with the original refresh token; the others take up its result
    # instead of renewing again with the token it rotated out.
    assert used == ["r0"]
    assert tokens == ["a-r0"] * 3
    assert state["refresh_token"] == "r0+"


# A client that adds its own entries to a shared list, as the stream sessions are kept.
APPENDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from resources.lib import provider

profile, start, name = sys.argv[2], float(sys.argv[3]), sys.argv[4]
client = provider.Client(profile)
time.sleep(max(0, start - time.time()))
for i in range(5):
    with client.state.lock():
        client.state.save()  # what the others added meanwhile
        client.state["open_sessions"] = (client.state.get("open_sessions") or []) + ["%s%d" % (name, i)]
        time.sleep(0.02)
        client.state.save()
"""


def test_clients_in_separate_interpreters_keep_each_others_list_entries(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    worker = tmp_path / "appender.py"
    worker.write_text(APPENDER)
    start = time.time() + 1.5
    procs = [
        subprocess.Popen([sys.executable, str(worker), ROOT, str(profile), str(start), name], stderr=subprocess.PIPE, text=True)
        for name in "abc"
    ]
    for p in procs:
        _, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    kept = json.loads((profile / "session.json").read_text())["open_sessions"]
    assert sorted(kept) == sorted("%s%d" % (n, i) for n in "abc" for i in range(5))


def test_a_lock_not_had_in_time_lets_the_work_go_on(tmp_path, monkeypatch):
    state_file = str(tmp_path / core.STATE_FILE)
    other = statefile._lock_file(state_file + ".lock")  # another interpreter's turn, never ending
    assert other is not None
    lock_wait = 0.2
    monkeypatch.setattr(statefile, "LOCK_WAIT", lock_wait)
    try:
        began = time.monotonic()
        with statefile.state_lock(state_file), statefile.state_lock(state_file):  # re-entrant meanwhile
            pass
        assert lock_wait <= time.monotonic() - began < 5
        assert statefile._FILE_LOCKS == {}
    finally:
        statefile._unlock_file(other)


def test_a_lock_wait_gives_up_at_once_when_kodi_exits(tmp_path):
    state_file = str(tmp_path / core.STATE_FILE)
    other = statefile._lock_file(state_file + ".lock")
    waits = []
    kodi_exiting = lambda seconds: waits.append(seconds) or True  # noqa: E731
    try:
        began = time.monotonic()
        with statefile.state_lock(state_file, kodi_exiting):
            pass
        assert time.monotonic() - began < 1 and waits == [statefile.LOCK_RETRY]  # not the whole LOCK_WAIT
    finally:
        statefile._unlock_file(other)


def _two_clients(tmp_path):
    """Two clients' states read from the same file."""
    path = str(tmp_path / core.STATE_FILE)
    return path, statefile.State(path), statefile.State(path)


def test_saving_keeps_what_other_clients_wrote(tmp_path):
    path, first, second = _two_clients(tmp_path)
    first["refresh_token"] = "rotated"
    first.save()
    # The second client still holds the file as it was; its own change goes in, the renewal stays.
    second["pin_key"] = "KEY"
    second.save()
    third = statefile.State(path)
    assert third["refresh_token"] == "rotated" and third["pin_key"] == "KEY"
    assert second["refresh_token"] == "rotated"  # taken up when it saved


def test_saving_drops_only_the_keys_this_client_removed(tmp_path):
    path = str(tmp_path / core.STATE_FILE)
    first = statefile.State(path)
    first.update(refresh_token="r", account={"a": 1})
    first.save()
    second = statefile.State(path)
    first["pin_key"] = "KEY"
    first.save()
    del second["account"]
    second.save()
    assert statefile.State(path) == {"refresh_token": "r", "pin_key": "KEY"}


def test_taking_up_others_changes_writes_nothing(tmp_path):
    path, first, second = _two_clients(tmp_path)
    first["refresh_token"] = "rotated"
    first.save()
    written = os.stat(path).st_mtime_ns
    os.utime(path, ns=(written - 10**9, written - 10**9))
    second.save()
    assert second["refresh_token"] == "rotated"
    assert os.stat(path).st_mtime_ns == written - 10**9  # read, not written again
