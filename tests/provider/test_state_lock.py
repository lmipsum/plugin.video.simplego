"""The state file shared by separate interpreters: the service and each plugin run.

Kodi runs them in interpreters of their own (on Android in one OS process), so a lock
in Python's memory does not keep them apart; these tests run real separate processes.
"""

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# One client of the shared state: waits for a common start, then asks for the access
# token. The renewal is a stand-in that rotates the refresh token as Keycloak does,
# and logs which refresh token it was given.
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
    time.sleep(0.5)  # the redirect chain to the STS
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
    from resources.lib.provider import statefile

    state_file = str(tmp_path / "session.json")
    other = statefile._lock_file(state_file + ".lock")  # another interpreter's turn, never ending
    assert other is not None
    monkeypatch.setattr(statefile, "LOCK_WAIT", 0.2)
    try:
        began = time.monotonic()
        with statefile.state_lock(state_file), statefile.state_lock(state_file):  # re-entrant meanwhile
            pass
        assert 0.2 <= time.monotonic() - began < 5
        assert statefile._FILE_LOCKS == {}
    finally:
        statefile._unlock_file(other)


def test_a_lock_wait_gives_up_at_once_when_kodi_exits(tmp_path, monkeypatch):
    from resources.lib.provider import statefile

    state_file = str(tmp_path / "session.json")
    other = statefile._lock_file(state_file + ".lock")
    waits = []
    kodi_exiting = lambda seconds: waits.append(seconds) or True  # noqa: E731
    try:
        began = time.monotonic()
        with statefile.state_lock(state_file, kodi_exiting):
            pass
        assert time.monotonic() - began < 1 and waits == [0.05]  # not LOCK_WAIT's 45 s
    finally:
        statefile._unlock_file(other)
