"""The pull request rules (see scripts/pr_rules.py)."""

import importlib.util
import os

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "pr_rules.py")
spec = importlib.util.spec_from_file_location("pr_rules", SCRIPT)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

DIFF = """--- a/x.py
+++ b/x.py
-    # TODO(#4): show a row as expired
+    expired = True
"""


def check(title="feat: rows say when they expire", body="Closes #4", diff=DIFF, open_issues=(4, 21), base="dev"):
    return rules.broken(base, "build/x", title, body, diff, list(open_issues))


def test_a_typed_pull_request_closing_its_issue_passes():
    assert check() == []
    assert check(title="fix(play): x", body="Fixes #4 and resolves #21") == []


def test_one_closing_no_issue_or_a_closed_one_fails():
    assert check(body="Refs #4") == [
        'the body closes no issue ("Closes #N")',
        "TODO(#4) is taken out, but #4 is not closed by it",
    ]
    assert check(body="Closes #4, closes #5") == ["#5 is not an open issue"]


def test_a_todo_taken_out_must_be_closed():
    # The 2026-11-15 miss: TODO(#4) went with the change, #4 stayed open.
    assert check(body="Closes #21") == ["TODO(#4) is taken out, but #4 is not closed by it"]
    moved = DIFF + "+    # TODO(#4): moved here\n"
    assert check(body="Closes #21", diff=moved) == []  # moved, not taken out


def test_an_untyped_title_fails():
    assert check(title="Continue watching rows") == [
        'the title is not a typed subject ("fix: ...", "feat: ..."): Continue watching rows'
    ]


def test_a_private_address_added_fails():
    # Put together here: written whole, this file's own pull request would add one.
    home, office = "192.168" + ".1.2", "10.0" + ".0.2"
    assert check(diff=DIFF + "+adb connect %s:5555\n" % home) == ["a private address is added: %s" % home]
    assert check(diff=DIFF + "-adb connect %s:5555\n" % office) == []  # taken out: fine


def test_only_dev_goes_into_main():
    assert rules.broken("main", "dev", "Release", "", "", []) == []
    assert rules.broken("main", "build/x", "x", "", "", []) == ["only dev goes into main (a release), not build/x"]
