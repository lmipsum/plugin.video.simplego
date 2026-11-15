#!/usr/bin/env python3
"""Check a pull request against the repository's rules; the pr-rules workflow runs it on every pull request.

    pr_rules.py <base> <head>    reads the PR's title and body from PR_TITLE and PR_BODY, its diff
                                 from git, the open issues from OPEN_ISSUES ("4 21 ...")

Into dev (squash-merged: the title is the commit's subject, the body its message, see the dev ruleset):
- the title is a typed subject ("fix: ...", "feat(scope): ..."): feat: and fix: become the add-on's news;
- the body closes at least one open issue ("Closes #4"), which closes it once the commit reaches main;
- every TODO(#N) the diff takes out is closed by it too;
- no added line has a private IPv4 address (a device's address stays out of the public repository).
Into main: only from dev (a release; its commits passed the rules above).
Prints each broken rule; exits 1 if any.
"""

import os
import re
import subprocess
import sys

TYPED = re.compile(r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|style|test)(?:\([^)]+\))?!?: \S")
CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #(\d+)\b", re.I)
TODO = re.compile(r"TODO\(#(\d+)\)")
PRIVATE_IP = re.compile(r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b")


def broken(base, head, title, body, diff, open_issues):
    """Return the broken rules' descriptions ([] if none).

    :param diff: the PR's unified diff against the base
    :param open_issues: the numbers of the open issues
    """
    if base == "main":
        return [] if head == "dev" else ["only dev goes into main (a release), not %s" % head]
    if base != "dev":
        return []
    out = []
    if not TYPED.match(title):
        out.append('the title is not a typed subject ("fix: ...", "feat: ..."): %s' % title)
    closed = {int(n) for n in CLOSES.findall(body)}
    if not closed:
        out.append('the body closes no issue ("Closes #N")')
    for number in sorted(closed - set(open_issues)):
        out.append("#%d is not an open issue" % number)
    removed = {int(n) for n in TODO.findall(_lines(diff, "-"))} - {int(n) for n in TODO.findall(_lines(diff, "+"))}
    for number in sorted(removed - closed):
        out.append("TODO(#%d) is taken out, but #%d is not closed by it" % (number, number))
    for address in sorted(set(PRIVATE_IP.findall(_lines(diff, "+")))):
        out.append("a private address is added: %s" % address)
    return out


def _lines(diff, sign):
    """Return a diff's added ("+") or removed ("-") lines, its file headers left out."""
    return "\n".join(line[1:] for line in diff.splitlines() if line.startswith(sign) and not line.startswith(sign * 3))


def main(argv):
    if len(argv) != 2:
        sys.stderr.write(__doc__)
        return 2
    base, head = argv
    diff = subprocess.run(["git", "diff", "origin/%s...HEAD" % base], capture_output=True, text=True, check=True).stdout
    problems = broken(
        base,
        head,
        os.environ.get("PR_TITLE", ""),
        os.environ.get("PR_BODY", ""),
        diff,
        [int(n) for n in os.environ.get("OPEN_ISSUES", "").split()],
    )
    for problem in problems:
        print("::error::%s" % problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
