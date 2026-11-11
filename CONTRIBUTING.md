# Contributing to plugin.video.simplego

Thanks for considering a contribution! These are guidelines, not hard rules;
use your best judgment and feel free to propose changes to this document.

## What belongs here

The add-on plays Telekom TV GO with the user's own subscription. Changes are welcome when they:

- follow a change of the web player or the backend it talks to;
- add a feature the web player has (catch-up, recordings, more of the guide);
- fix a bug, improve tests or documentation, or support another Kodi version or platform.

Out of scope: anything that bypasses the subscription, the login's reCAPTCHA,
the geo-restriction, the concurrent stream limit or the DRM.

## Getting started

```bash
python -m pip install -r requirements-dev.txt
pip install pre-commit && pre-commit install
python -m pytest
python scripts/build_zip.py
```

On an Android TV device with the add-on installed and logged in (adb connected; in Kodi, debug
logging and *Allow remote control from applications on this system* on):

```bash
python scripts/device_check.py --device <device-ip>:5555 --background
```

## Style

- Follow the existing code: ruff (`ruff check`, `ruff format`) with the settings in `ruff.toml`.
- Keep the code Python 3.8 compatible: Kodi 20 (Nexus), the oldest supported, runs on it.
- Explain *why* in comments where the platform forces something unusual.
- Add or update tests for every behaviour change outside Kodi-only code.
- Write code, comments, commit messages and issues in English.
- Start commit subjects with a [Conventional Commits](https://www.conventionalcommits.org/) type.
  `feat:` and `fix:` subjects become the add-on's news at the next release, so write them for users
  (`feat: remove expired rows from Continue watching`); `refactor:`, `test:`, `ci:`, `docs:` stay out.

## No secrets, no personal setups

Never commit tokens, login redirect URLs, account or device identifiers, IP
addresses or logs that contain them — not even as examples. Use placeholders such
as `aaaa.bbbb.cccc`. The pre-commit hook and CI refuse anything shaped like a token.

## Pull requests

Open pull requests against the `dev` branch. CI must be green before review.

## Releases

Raise the version in `addon.xml` on `dev`, merge `dev` into `main`, then run the *release* workflow on
`main`: it writes the news, tags the commit and publishes the zip. Merge `main` back into `dev`.
To try a branch on a device first, run the *build* workflow on it and take the zip from its artifacts.
