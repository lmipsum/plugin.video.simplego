#!/usr/bin/env python3
"""Build the installable add-on zip: dist/plugin.video.simplego-<version>.zip.

build_zip.py            the zip; only what Kodi needs goes in (tests, scripts, CI and docs stay out)
build_zip.py version    the add-on's version, from addon.xml
"""

import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE = ["addon.xml", "default.py", "service.py", "LICENSE.txt", "resources"]


def folder_identity(folder):
    """Return (id, version) of an add-on folder's addon.xml."""
    with open(os.path.join(folder, "addon.xml"), encoding="utf-8") as f:
        head = re.search(r"<addon\b[^>]*>", f.read()).group(0)
    return re.search(r'\bid="([^"]+)"', head).group(1), re.search(r'\bversion="([^"]+)"', head).group(1)


def zip_folder(folder, out_dir, include=None):
    """Zip an add-on folder as Kodi installs it (<id>/... inside), without compiled Python; return the zip's path.

    :param include: the files and folders to take, relative to the folder; None for all
    """
    addon_id, version = folder_identity(folder)
    out = os.path.join(out_dir, "%s-%s.zip" % (addon_id, version))
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(_files(folder, include)):
            z.write(path, "%s/%s" % (addon_id, os.path.relpath(path, folder).replace(os.sep, "/")))
    return out


def _files(folder, include):
    """Yield the paths of the files to zip under folder."""
    for item in include or [""]:
        path = os.path.join(folder, item)
        if os.path.isfile(path):
            yield path
            continue
        for d, _, files in os.walk(path):
            if "__pycache__" not in d:
                yield from (os.path.join(d, name) for name in files if not name.endswith(".pyc"))


def main(argv):
    if not argv:
        print(zip_folder(ROOT, os.path.join(ROOT, "dist"), INCLUDE))
        return 0
    if argv == ["version"]:
        print(folder_identity(ROOT)[1])
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
