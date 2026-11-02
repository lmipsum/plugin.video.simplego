"""The Kodi repository's served folder: zips by add-on, their assets, addons.xml and its md5."""

import hashlib
import importlib.util
import os
import re
import zipfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "build_repo.py")
spec = importlib.util.spec_from_file_location("build_repo", SCRIPT)
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)

PLUGIN = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<addon id="plugin.video.x" name="X" version="%s">\n'
    "    <extension><assets><icon>resources/icon.png</icon></assets></extension>\n</addon>\n"
)


def plugin_zip(tmp_path, version):
    path = tmp_path / ("plugin.video.x-%s.zip" % version)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("plugin.video.x/addon.xml", PLUGIN % version)
        z.writestr("plugin.video.x/resources/icon.png", b"png")
        z.writestr("plugin.video.x/default.py", "")
    return str(path)


def test_the_repository_add_on_zips_as_kodi_installs_it(tmp_path):
    root = os.path.dirname(SCRIPT)
    out = repo.zip_folder(os.path.join(os.path.dirname(root), repo.REPOSITORY), str(tmp_path))
    with zipfile.ZipFile(out) as z:
        assert {"repository.lmipsum/addon.xml", "repository.lmipsum/icon.png"} <= set(z.namelist())
    assert os.path.basename(out).startswith("repository.lmipsum-")


def test_published_add_ons_are_listed_with_their_assets_and_a_changing_checksum(tmp_path):
    pages = tmp_path / "pages"
    repository = repo.zip_folder(os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), repo.REPOSITORY), str(tmp_path))
    repo.publish(str(pages), [plugin_zip(tmp_path, "1.0.0"), repository])
    assert (pages / "plugin.video.x" / "plugin.video.x-1.0.0.zip").is_file()
    assert (pages / "plugin.video.x" / "resources" / "icon.png").read_bytes() == b"png"
    index = (pages / "addons.xml").read_text(encoding="utf-8")
    assert index.count("<addon ") == 2 and 'version="1.0.0"' in index and "<?xml" not in index.split("<addons>")[1]
    assert (pages / "addons.xml.md5").read_text() == hashlib.md5(index.encode("utf-8")).hexdigest()
    # A link Kodi's file manager lists: its text is its address.
    links = re.findall(r'<a href="([^"]+)">([^<]+)</a>', (pages / "index.html").read_text(encoding="utf-8"))
    href, text = links[0]
    assert len(links) == 1 and href == text
    assert href.startswith("repository.lmipsum/repository.lmipsum-") and href.endswith(".zip")
    first = (pages / "addons.xml.md5").read_text()
    # A new version: listed instead of the old one, its zip beside the old.
    repo.publish(str(pages), [plugin_zip(tmp_path, "1.0.1")])
    index = (pages / "addons.xml").read_text(encoding="utf-8")
    assert 'id="plugin.video.x" name="X" version="1.0.1"' in index and index.count('id="plugin.video.x"') == 1
    assert (pages / "plugin.video.x" / "plugin.video.x-1.0.0.zip").is_file()
    assert (pages / "addons.xml.md5").read_text() != first
