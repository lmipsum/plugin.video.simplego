"""The installable zip: what goes in, and the version the release reads."""

import importlib.util
import os
import zipfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "build_zip.py")
spec = importlib.util.spec_from_file_location("build_zip", SCRIPT)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

PLUGIN = '<?xml version="1.0" encoding="UTF-8"?>\n<addon id="plugin.video.x" name="X" version="%s">\n</addon>\n'


def test_only_the_included_files_go_in_without_compiled_python(tmp_path):
    folder = tmp_path / "addon"
    (folder / "resources" / "__pycache__").mkdir(parents=True)
    (folder / "addon.xml").write_text(PLUGIN % "1.0.0", encoding="utf-8")
    (folder / "resources" / "a.py").write_text("", encoding="utf-8")
    (folder / "resources" / "b.pyc").write_bytes(b"")
    (folder / "resources" / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"")
    (folder / "tests.py").write_text("", encoding="utf-8")
    out = build.zip_folder(str(folder), str(tmp_path / "dist"), ["addon.xml", "resources"])
    assert os.path.basename(out) == "plugin.video.x-1.0.0.zip"
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["plugin.video.x/addon.xml", "plugin.video.x/resources/a.py"]


def test_the_version_command_says_the_add_ons_version(capsys):
    assert build.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == build.folder_identity(build.ROOT)[1]
    assert build.main(["nonsense"]) == 2
