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


def test_only_the_included_files_go_in_without_compiled_python(tmp_path):
    folder = tmp_path / "addon"
    (folder / "resources" / "__pycache__").mkdir(parents=True)
    (folder / "addon.xml").write_text(PLUGIN % "1.0.0", encoding="utf-8")
    (folder / "resources" / "a.py").write_text("", encoding="utf-8")
    (folder / "resources" / "b.pyc").write_bytes(b"")
    (folder / "resources" / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"")
    (folder / "tests.py").write_text("", encoding="utf-8")
    out = repo.zip_folder(str(folder), str(tmp_path / "dist"), ["addon.xml", "resources"])
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["plugin.video.x/addon.xml", "plugin.video.x/resources/a.py"]


def test_the_version_command_runs():
    assert repo.main(["version"]) == 0


def _publish(tmp_path):
    """Publish version 1.0.0 of an add-on and the repository add-on; the served folder."""
    pages = tmp_path / "pages"
    repository = repo.zip_folder(os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), repo.REPOSITORY), str(tmp_path))
    repo.publish(str(pages), [plugin_zip(tmp_path, "1.0.0"), repository])
    return pages


def _links(pages):
    """Return the served index page's links as (address, text)."""
    return re.findall(r'<a href="([^"]+)">([^<]+)</a>', (pages / "index.html").read_text(encoding="utf-8"))


def test_a_published_add_on_is_served_with_its_assets(tmp_path):
    pages = _publish(tmp_path)
    assert (pages / "plugin.video.x" / "plugin.video.x-1.0.0.zip").is_file()
    assert (pages / "plugin.video.x" / "resources" / "icon.png").read_bytes() == b"png"


def test_the_published_add_ons_are_listed_with_their_checksum(tmp_path):
    pages = _publish(tmp_path)
    index = (pages / "addons.xml").read_text(encoding="utf-8")
    assert index.count("<addon ") == 2 and 'version="1.0.0"' in index and "<?xml" not in index.split("<addons>")[1]
    assert (pages / "addons.xml.md5").read_text() == hashlib.md5(index.encode("utf-8")).hexdigest()


def test_each_link_on_the_index_page_says_its_address(tmp_path):
    # Kodi's file manager lists a link by its text.
    assert all(href == text for href, text in _links(_publish(tmp_path)))


def test_the_index_page_links_the_repository_zip_and_the_files_the_repository_reads(tmp_path):
    # A file the repository reads that is not linked goes missing from Kodi's kept listing.
    hrefs = [href for href, _ in _links(_publish(tmp_path))]
    assert hrefs[0].startswith("repository.lmipsum/repository.lmipsum-") and hrefs[0].endswith(".zip")
    assert hrefs[1:] == ["addons.xml", "addons.xml.md5"]


def test_a_new_version_is_listed_instead_of_the_old_one_its_zip_beside_the_old(tmp_path):
    pages = _publish(tmp_path)
    first = (pages / "addons.xml.md5").read_text()
    repo.publish(str(pages), [plugin_zip(tmp_path, "1.0.1")])
    index = (pages / "addons.xml").read_text(encoding="utf-8")
    assert 'id="plugin.video.x" name="X" version="1.0.1"' in index and index.count('id="plugin.video.x"') == 1
    assert (pages / "plugin.video.x" / "plugin.video.x-1.0.0.zip").is_file()
    assert (pages / "addons.xml.md5").read_text() != first
