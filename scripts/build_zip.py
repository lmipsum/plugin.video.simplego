#!/usr/bin/env python3
"""Build the installable add-on zip: dist/plugin.video.simplego-<version>.zip.

Only what Kodi needs goes in; tests, scripts, CI and docs stay out.
"""

import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE = ["addon.xml", "default.py", "service.py", "LICENSE.txt", "resources"]


def main():
    with open(os.path.join(ROOT, "addon.xml"), encoding="utf-8") as f:
        xml = f.read()
    addon_id = re.search(r'<addon id="([^"]+)"', xml).group(1)
    version = re.search(r'<addon [^>]*version="([^"]+)"', xml).group(1)
    out = os.path.join(ROOT, "dist", "%s-%s.zip" % (addon_id, version))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in INCLUDE:
            path = os.path.join(ROOT, item)
            files = (
                [path]
                if os.path.isfile(path)
                else [
                    os.path.join(d, f)
                    for d, dirs, fs in os.walk(path)
                    for f in fs
                    if "__pycache__" not in d and not f.endswith(".pyc")
                ]
            )
            for file in sorted(files):
                z.write(file, "%s/%s" % (addon_id, os.path.relpath(file, ROOT).replace(os.sep, "/")))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
