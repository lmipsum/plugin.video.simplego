#!/usr/bin/env python3
"""Build the Kodi repository: the repository add-on's zip, and the folder GitHub Pages serves.

    build_repo.py zip <add-on folder>            dist/<id>-<version>.zip of a plain add-on folder
    build_repo.py publish <pages folder> <zip>... add the zips to the served folder, rewrite its index

The served folder's layout is Kodi's (https://kodi.wiki/view/Add-on_repositories): <id>/<id>-<version>.zip
with the add-on's assets beside it, addons.xml (every add-on's addon.xml) and its md5. The release workflow
runs both on the gh-pages branch; repository.lmipsum points Kodi there.
"""

import hashlib
import html
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = re.compile(r"<addon\b.*</addon>", re.S)
# The repository add-on, linked from the served folder's index page for a first install.
REPOSITORY = "repository.lmipsum"


def identity(addon_xml):
    """Return (id, version) of an addon.xml's text."""
    head = re.search(r"<addon\b[^>]*>", addon_xml).group(0)
    return re.search(r'\bid="([^"]+)"', head).group(1), re.search(r'\bversion="([^"]+)"', head).group(1)


def zip_folder(folder, out_dir):
    """Zip an add-on folder as Kodi installs it (<id>/... inside); return the zip's path."""
    with open(os.path.join(folder, "addon.xml"), encoding="utf-8") as f:
        addon_id, version = identity(f.read())
    out = os.path.join(out_dir, "%s-%s.zip" % (addon_id, version))
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d, _, files in os.walk(folder):
            for name in sorted(files):
                path = os.path.join(d, name)
                z.write(path, "%s/%s" % (addon_id, os.path.relpath(path, folder).replace(os.sep, "/")))
    return out


def publish(pages, zips):
    """Add add-on zips to the served folder: each zip, its addon.xml and assets; then the index files."""
    for path in zips:
        with zipfile.ZipFile(path) as z:
            addon_xml = next(n for n in z.namelist() if n.count("/") == 1 and n.endswith("/addon.xml"))
            text = z.read(addon_xml).decode("utf-8")
            addon_id, version = identity(text)
            target = os.path.join(pages, addon_id)
            os.makedirs(target, exist_ok=True)
            shutil.copyfile(path, os.path.join(target, "%s-%s.zip" % (addon_id, version)))
            with open(os.path.join(target, "addon.xml"), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            # Kodi shows a repository's add-ons with the assets beside their zips, at their addon.xml paths.
            for asset in re.findall(r"<(?:icon|fanart|banner|clearlogo|screenshot)>([^<]+)<", text):
                name = "%s/%s" % (addon_id, asset.strip())
                if name in z.namelist():
                    out = os.path.join(target, *asset.strip().split("/"))
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with open(out, "wb") as f:
                        f.write(z.read(name))
    write_index(pages)


def write_index(pages):
    """Write addons.xml from the served add-ons' addon.xml, its md5, and an index page linking them and the repository zip."""
    addons, links = [], []
    for addon_id in sorted(os.listdir(pages)):
        path = os.path.join(pages, addon_id, "addon.xml")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        addons.append(ADDON.search(text).group(0))
        if addon_id == REPOSITORY:
            links.append("%s/%s-%s.zip" % ((addon_id,) + identity(text)))
    index = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n%s\n</addons>\n' % "\n".join(addons)
    with open(os.path.join(pages, "addons.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(index)
    with open(os.path.join(pages, "addons.xml.md5"), "w", encoding="utf-8", newline="\n") as f:
        f.write(hashlib.md5(index.encode("utf-8")).hexdigest())  # noqa: S324 - Kodi's change marker, not security
    # Kodi's file manager lists a web source by its links: the page Pages serves for the folder. It lists
    # a link only if its text is its address (how it tells a server's file listing), and keeps the listing:
    # a file of the folder missing from it does not open, so the repository's own files are listed too,
    # or the repository fails until Kodi restarts. See NameMatchesLink in
    # https://github.com/xbmc/xbmc/blob/Omega/xbmc/filesystem/HTTPDirectory.cpp and g_directoryCache in File.cpp.
    links += ["addons.xml", "addons.xml.md5"]
    with open(os.path.join(pages, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        anchors = ('<a href="%s">%s</a>' % ((html.escape(name),) * 2) for name in links)
        f.write("<!DOCTYPE html>\n<html><body>\n%s\n</body></html>\n" % "\n".join(anchors))
    # Pages would run Jekyll otherwise, which serves no file or folder starting with "_".
    open(os.path.join(pages, ".nojekyll"), "w").close()


def main(argv):
    if len(argv) == 2 and argv[0] == "zip":
        print(zip_folder(os.path.join(ROOT, argv[1]), os.path.join(ROOT, "dist")))
        return 0
    if len(argv) >= 3 and argv[0] == "publish":
        publish(argv[1], argv[2:])
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
