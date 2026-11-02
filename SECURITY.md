# Security Policy

plugin.video.simplego stores a long-lived Telekom login (refresh token) on the
Kodi device and, while a login dialog is open, accepts it over the local network.
Please report anything that could leak a login, let someone else log a device in,
or expose the account, privately.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/lmipsum/plugin.video.simplego/security/advisories/new).
Please do not open a public issue for security problems.

Include what you found, how to reproduce it, and the version (commit) you
tested. Redact tokens, login URLs, account and device identifiers from logs.

## Supported versions

Only the latest release receives fixes.
