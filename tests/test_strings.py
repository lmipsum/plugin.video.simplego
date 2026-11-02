"""The add-on's own strings (strings.po): each one used somewhere, each one used there, each translated."""

import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGUAGE = os.path.join(ROOT, "resources", "language", "resource.language.%s", "strings.po")
# The add-on's own string ids: 30000-30999 (Kodi's own are outside, as 38209, used as Kodi's).
OWN = re.compile(r"\b30\d{3}\b")


def _po(lang):
    """Return {id: (msgid, msgstr)} of a language's strings.po."""
    with open(LANGUAGE % lang, encoding="utf-8") as f:
        text = f.read()
    entries = re.findall(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"', text)
    return {int(i): (msgid, msgstr) for i, msgid, msgstr in entries}


def _used():
    """Return the own string ids the code, the settings and addon.xml name."""
    paths = glob.glob(os.path.join(ROOT, "resources", "lib", "**", "*.py"), recursive=True)
    paths += [os.path.join(ROOT, name) for name in ("default.py", "service.py", "addon.xml")]
    paths.append(os.path.join(ROOT, "resources", "settings.xml"))
    used = set()
    for path in paths:
        with open(path, encoding="utf-8") as f:
            used.update(int(n) for n in OWN.findall(f.read()))
    return used


def test_every_string_is_used_and_every_used_one_exists():
    strings, used = set(_po("en_gb")), _used()
    assert sorted(strings - used) == [], "strings no code, setting or addon.xml uses"
    assert sorted(used - strings) == [], "string ids used but not in strings.po"


def test_every_string_is_translated_to_hungarian():
    english, hungarian = _po("en_gb"), _po("hu_hu")
    assert set(english) == set(hungarian)
    assert [i for i, (msgid, _) in hungarian.items() if msgid != english[i][0]] == [], "msgid differs from English"
    assert [i for i, (_, msgstr) in hungarian.items() if not msgstr] == [], "no Hungarian text"
