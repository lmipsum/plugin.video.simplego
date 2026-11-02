"""The release's news: user-facing commits only, newest version first, within Kodi's limit."""

import importlib.util
import os

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "update_news.py")
spec = importlib.util.spec_from_file_location("update_news", SCRIPT)
news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(news)

XML = "<addon>\n    <extension>\n        <assets>\n        </assets>\n    </extension>\n</addon>\n"


def test_only_features_and_fixes_make_the_news_without_their_prefixes():
    subjects = [
        "feat: remove expired rows from Continue watching",
        "refactor: split the views",
        "fix(play): audio sync",
        "docs: x",
    ]
    assert news.changes(subjects) == ["Remove expired rows from Continue watching", "Audio sync"]
    assert news.block("1.0.1", "2026-11-02", []) == "v1.0.1 (2026-11-02)\n- Maintenance update."


def test_a_new_version_comes_first_and_old_ones_only_as_far_as_kodi_allows():
    old = "v1.0.0 (2026-10-01)\n- First\n\n" + "v0.9.0 (2026-09-01)\n- " + "x" * news.LIMIT
    merged = news.merged("v1.0.1 (2026-11-02)\n- New", old)
    assert merged == "v1.0.1 (2026-11-02)\n- New\n\nv1.0.0 (2026-10-01)\n- First"
    # Run again for the same version (a release retried): its block is not doubled.
    assert news.merged("v1.0.1 (2026-11-02)\n- New", merged).count("v1.0.1") == 1


def test_the_news_goes_into_addon_xml_escaped_and_replaces_the_old():
    xml = news.with_news(XML, "v1 (d)\n- A & B")
    assert "</assets>\n        <news>v1 (d)\n- A &amp; B</news>\n    </extension>" in xml
    assert news.with_news(xml, "v2").count("<news>") == 1 and "<news>v2</news>" in news.with_news(xml, "v2")
