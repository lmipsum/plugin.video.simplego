#!/usr/bin/env python3
"""Put this version's changes into addon.xml's <news>: the feat: and fix: commits since the last version tag.

The release workflow runs it before tagging (see .github/workflows/release.yml) and commits the result.
Other commits (refactor:, test:, ci:, docs: ...) tell users nothing and stay out. Kodi shows the news on
the add-on's page; kodi-addon-checker warns over LIMIT characters, so older versions' blocks go first.
Prints this version's block, for the release notes.
"""

import datetime
import os
import re
import subprocess
import sys
from xml.sax.saxutils import escape
from xml.sax.saxutils import unescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 1500
# A Conventional Commits subject that users would care about: "feat: ..." or "fix(scope): ...".
USER_FACING = re.compile(r"^(?:feat|fix)(?:\([^)]*\))?!?:\s*(.+)$")
NEWS = re.compile(r"\n?[ \t]*<news>(.*?)</news>", re.S)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def last_tag():
    """Return the latest version tag reachable from HEAD; None before the first release."""
    found = git("describe", "--tags", "--abbrev=0", "--match", "v*")
    return found.stdout.strip() if found.returncode == 0 else None


def changes(subjects):
    """Return the user-facing lines of commit subjects, their prefixes dropped, oldest first."""
    found = [USER_FACING.match(s.strip()) for s in subjects]
    return [m.group(1)[:1].upper() + m.group(1)[1:] for m in found if m]


def block(version, date, lines):
    """Return one version's news: a heading line, then its changes."""
    return "v%s (%s)\n%s" % (version, date, "\n".join("- " + line for line in lines or ["Maintenance update."]))


def merged(new, old):
    """Return the new block followed by as many older blocks as fit in LIMIT."""
    out = new
    for older in (b.strip() for b in old.split("\n\n")):
        if older and not older.startswith(new.split("\n", 1)[0]) and len(out) + 2 + len(older) <= LIMIT:
            out += "\n\n" + older
    return out[:LIMIT]


def with_news(xml, news):
    """Return addon.xml with its <news> replaced (or added after <assets>)."""
    element = "\n        <news>%s</news>" % escape(news)
    if NEWS.search(xml):
        return NEWS.sub(lambda m: element, xml, count=1)
    return xml.replace("</assets>", "</assets>" + element, 1)


def main():
    path = os.path.join(ROOT, "addon.xml")
    with open(path, encoding="utf-8") as f:
        xml = f.read()
    version = re.search(r'<addon [^>]*version="([^"]+)"', xml).group(1)
    since = last_tag()
    log = git("log", "--no-merges", "--reverse", "--format=%s", *(["%s..HEAD" % since] if since else []))
    if log.returncode:
        sys.stderr.write(log.stderr)
        return 1
    new = block(version, datetime.date.today().isoformat(), changes(log.stdout.splitlines()))
    old = NEWS.search(xml)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(with_news(xml, merged(new, unescape(old.group(1)) if old else "")))
    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
