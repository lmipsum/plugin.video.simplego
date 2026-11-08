"""A JSON file several clients read and write: each sees the others' changes, none loses them."""

import contextlib
import json

from resources.lib.util import sharedfile


def _shared(tmp_path, locks):
    @contextlib.contextmanager
    def lock():
        locks.append(1)
        yield

    return sharedfile.SharedJson(str(tmp_path / "shared.json"), lock)


def test_a_missing_file_reads_empty(tmp_path):
    assert _shared(tmp_path, []).read() == {}


def test_each_client_sees_the_others_changes_and_keeps_them(tmp_path):
    locks = []
    first, second = _shared(tmp_path, locks), _shared(tmp_path, locks)
    assert second.read() == {}
    first.change(lambda content: content.update(a=1))
    second.change(lambda content: content.update(b=2))  # on what the file has now: a stays
    assert first.read() == {"a": 1, "b": 2}
    assert json.loads((tmp_path / "shared.json").read_text()) == {"a": 1, "b": 2}
    assert len(locks) == 2  # every change under the lock


def test_an_unchanged_file_is_not_read_again(tmp_path, monkeypatch):
    shared = _shared(tmp_path, [])
    shared.change(lambda content: content.update(a=1))
    reads = []
    real = sharedfile._read
    monkeypatch.setattr(sharedfile, "_read", lambda path: reads.append(path) or real(path))
    assert shared.read() == {"a": 1} and shared.read() == {"a": 1}
    assert reads == []
