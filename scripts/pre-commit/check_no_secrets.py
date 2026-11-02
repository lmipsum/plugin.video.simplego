#!/usr/bin/env python3
"""Pre-commit guard: refuse staged content that looks like a credential of the provider's.

Catches refresh tokens (JWTs), MediaKind access tokens and token-bearing login URLs,
including in log excerpts. Runs on staged files as a hook and on every tracked file in CI.
"""

import re
import sys
from pathlib import Path

PATTERNS = [
    # JWT: header and payload are base64url JSON, so both start with "eyJ".
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),
    # MediaKind STS access token.
    re.compile(r"AuthToken1[A-Za-z0-9_\-]{40,}"),
    # A login redirect or header carrying a real-looking token value.
    re.compile(r"(?:access_token|refresh_token|bff_token|AuthorizationToken)[=:]\s*[\"']?[A-Za-z0-9_\-.]{40,}"),
]

# Files that define the patterns themselves.
ALLOWLISTED_PATHS = [re.compile(r"^scripts/pre-commit/check_no_secrets\.py$")]

BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".zip"}


def check(path):
    hits = []
    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return hits
    for n, line in enumerate(text.splitlines(), start=1):
        for pattern in PATTERNS:
            m = pattern.search(line)
            if m:
                hits.append((n, m.group(0)[:24] + "..."))
    return hits


def main(argv):
    failed = False
    for name in argv:
        rel = name.replace("\\", "/")
        if any(p.match(rel) for p in ALLOWLISTED_PATHS) or Path(rel).suffix.lower() in BINARY_SUFFIXES:
            continue
        for line, sample in check(Path(name)):
            print("%s:%d: looks like a credential: %s" % (rel, line, sample))
            failed = True
    if failed:
        print("Refusing: remove the token(s) above, use placeholders such as aaaa.bbbb.cccc.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
