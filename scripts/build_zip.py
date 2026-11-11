#!/usr/bin/env python3
"""Build the installable add-on zip: dist/plugin.video.simplego-<version>.zip.

Only what Kodi needs goes in; tests, scripts, CI and docs stay out.
"""

import os
import sys

from build_repo import ROOT
from build_repo import zip_folder

INCLUDE = ["addon.xml", "default.py", "service.py", "LICENSE.txt", "resources"]


def main():
    print(zip_folder(ROOT, os.path.join(ROOT, "dist"), INCLUDE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
