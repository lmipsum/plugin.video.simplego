"""The guide's blocks kept on disk: written whole or not at all, parsed again only when their file changes."""

import os

from resources.lib.provider import guideblocks
from resources.lib.util import atomicfile

DAY, OFFSET = "2026-10-27", 15


def test_a_block_whose_folder_is_missing_is_not_kept(tmp_path):
    path = guideblocks.block_path(str(tmp_path / "gone"), DAY, OFFSET)
    guideblocks.store_block(path, None, {"1001": []})  # fetched again next time
    assert not (tmp_path / "gone").exists()


def test_a_block_that_cannot_be_written_leaves_no_file_behind(tmp_path, monkeypatch):
    def full_disk(src, dst):
        raise OSError("No space left on device")

    monkeypatch.setattr(atomicfile.os, "replace", full_disk)
    guideblocks.store_block(guideblocks.block_path(str(tmp_path), DAY, OFFSET), None, {"1001": []})
    assert list(tmp_path.iterdir()) == []  # the half-written temp file is gone too


def test_a_block_read_again_is_not_parsed_again_until_its_file_changes(tmp_path, monkeypatch):
    path = guideblocks.block_path(str(tmp_path), DAY, OFFSET)
    guideblocks.store_block(path, None, {"1001": [{"start_time": "a"}]})
    parsed = []
    original = guideblocks.json.loads
    monkeypatch.setattr(guideblocks.json, "loads", lambda text: parsed.append(1) or original(text))
    assert guideblocks.read_channels(path, None) == guideblocks.read_channels(path, {"1001"})
    assert len(parsed) == 1
    guideblocks.store_block(path, None, {"1001": [{"start_time": "b"}]})
    os.utime(path, ns=(0, os.stat(path).st_mtime_ns + 10**9))  # fetched again
    assert guideblocks.read_channels(path, None)["1001"][0]["start_time"] == "b" and len(parsed) == 2
