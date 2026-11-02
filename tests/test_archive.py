"""What Kodi's add-on submitter packs (`git archive`, see .gitattributes) is what the release zip ships."""

import importlib.util
import io
import os
import subprocess
import tarfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("build_zip", os.path.join(ROOT, "scripts", "build_zip.py"))
build_zip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_zip)


def test_the_archive_holds_only_what_the_zip_ships():
    try:
        tar = subprocess.run(
            ["git", "archive", "--worktree-attributes", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    top = {name.split("/", 1)[0] for name in tarfile.open(fileobj=io.BytesIO(tar)).getnames()}
    assert top == set(build_zip.INCLUDE)
