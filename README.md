# Simple GO

[![Tests](https://img.shields.io/github/actions/workflow/status/lmipsum/plugin.video.simplego/tests.yml?branch=main&label=tests&style=plastic)](https://github.com/lmipsum/plugin.video.simplego/actions/workflows/tests.yml)
[![Secrets scan](https://img.shields.io/github/actions/workflow/status/lmipsum/plugin.video.simplego/secrets-scan.yml?branch=main&label=secrets%20scan&style=plastic)](https://github.com/lmipsum/plugin.video.simplego/actions/workflows/secrets-scan.yml)
[![Release](https://img.shields.io/github/v/release/lmipsum/plugin.video.simplego?style=plastic)](https://github.com/lmipsum/plugin.video.simplego/releases/latest)
[![License](https://img.shields.io/badge/dynamic/xml?url=https%3A%2F%2Fraw.githubusercontent.com%2Flmipsum%2Fplugin.video.simplego%2Fmain%2Faddon.xml&query=%2F%2Flicense&label=license&color=blue&style=plastic)](LICENSE.txt)
[![Kodi](https://img.shields.io/badge/dynamic/xml?url=https%3A%2F%2Fraw.githubusercontent.com%2Flmipsum%2Fplugin.video.simplego%2Fmain%2Faddon.xml&query=substring-before(%2F%2Fimport%5B%40addon%3D'inputstream.adaptive'%5D%2F%40version%2C'.')&suffix=%2B&label=Kodi&logo=kodi&logoColor=white&color=17B2E7&style=plastic)](https://kodi.tv/)
[![Ruff](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2Flmipsum%2Fplugin.video.simplego%2Fmain%2F.pre-commit-config.yaml&query=%24.repos%5B1%5D.rev&label=ruff&logo=ruff&logoColor=white&color=D7FF64&style=plastic)](https://github.com/astral-sh/ruff)

Simple GO (`plugin.video.simplego`) is an unofficial [Kodi](https://kodi.tv/) add-on for Magyar Telekom's
[TV GO](https://player.telekomtvgo.hu/) service: live TV and radio with your own subscription,
watching back, and, if you want it, the channels plus programme guide in Kodi's TV section.

This add-on is not affiliated with or endorsed by Magyar Telekom Nyrt. You need a valid Telekom TV GO
subscription; the add-on only does what the web player does with your own account.

## Where to watch

In the add-on's own lists under *Add-ons → Video add-ons*, and, once switched on in *Settings → TV menu*,
in Kodi's TV section with its programme guide (see [Kodi TV](#kodi-tv)). The two work side by side.

*Settings → General* applies to both: the guide's category colours, and the cast on the
information page, by programme type.

## Features

- Live TV and radio of your subscription, with what is on now and next; the web guide's channel
  lists and your favourite channels, in your account's own channel order.
- *Play from beginning* for the programme on air, from the channel's context menu, as far as the web
  player allows it.
- Watching back: your favourite programmes' airings in a picker (a series by its seasons), any
  programme of the last 7 days in the TV menu's guide.
- *Continue watching*: where you left a programme off, here or in the Telekom apps.
- Favourite channels and programmes, the channel order and watching positions are saved to your
  account, so the web and the mobile app show them too.
- Parental lock with the account's PIN, as in the Telekom apps: by age rating, per programme, wherever
  it plays. Kodi's own channel lock (*Settings → PVR & Live TV → Parental control*) is separate: it
  locks whole channels, in the TV section only.
- Login from a phone by QR code; Kodi counts as one device.

## Requirements

- Kodi 20 (Nexus) or newer, with InputStream Adaptive and InputStream Helper (installed automatically).
- A Widevine-capable device. The licence server decides which Kodi builds it accepts:

  | Platform | Status |
  |---|---|
  | Android TV / Google TV | Works (tested: Chromecast with Google TV, Kodi 21.2). |
  | Windows, macOS | Does not work: the licence server refuses Kodi's desktop Widevine module (code 3099). |

- A Hungarian internet address. Playback from abroad stops with code 7027; a VPN or proxy works only
  if it exits in Hungary (tested on Android with a Hungarian VPN endpoint).

## Installation

Through the add-on's Kodi repository, so that Kodi installs its updates too:

1. Download `repository.lmipsum-<version>.zip` from the
   [latest release](https://github.com/lmipsum/plugin.video.simplego/releases/latest).
2. In Kodi: *Settings → System → Add-ons*, enable *Unknown sources*.
3. *Settings → Add-ons → Install from zip file* and pick the zip.
4. *Install from repository → lmipsum repository → Video add-ons → Simple GO*.
5. On the first playback InputStream Helper offers to install Widevine; accept it.

Without updates: install `plugin.video.simplego-<version>.zip` from the same release in step 3 instead.

## Logging in

Choose *Log in* in the main menu. Scan the QR code with a phone on the same network, tap
*Log in with Telekom account*, log in with your TV GO e-mail address and password, then copy the
**web address** of the page you land on (not its text) and send it back on the add-on's page.
The login lasts about a year.

The login happens on a phone because the Telekom login page is protected by reCAPTCHA, which only
a real browser can complete, and Kodi has none. The add-on never sees your password, only the login
it gets back. A login through the web player instead would add that browser to your account's devices.

## Kodi TV

*Settings → TV menu → Show in the TV menu* (Off → On) installs IPTV Simple if needed and adds a
*Simple GO* source to Kodi's TV menu; switching it back off removes that source again. The guide
covers the days Kodi's own guide shows (*Settings → PVR & Live TV → Guide*), and the add-on refreshes
it in the background: on its schedule (*Refresh*), and right after you change something that affects
it. IPTV Simple reads the new files within an hour; *Settings → PVR & Live TV → Guide → Clear data*
shows them at once.

## Devices

Telekom allows only a few devices per account. *Log out* removes Kodi from the account, and
*Settings → General → My devices* lists the account's devices so you can remove the ones no longer used.

Log out before uninstalling the add-on: the device identity is kept with the add-on's data, so
uninstalling it together with its data without logging out leaves the old device on the account
(remove it under *My devices* from the new login, or in the provider's own apps).

## Troubleshooting

| Message | Cause |
|---|---|
| Playback is blocked outside Hungary (7027) | The Kodi device's internet address is not Hungarian, e.g. a VPN or proxy exiting abroad. |
| The licence server does not trust this device's Widevine module (3099) | Windows / macOS Kodi; see [Requirements](#requirements). |
| `max sessions for platform group exceeded` (2413) | Too many streams at once on the account (other devices, or a crashed Kodi's sessions not timed out yet). |
| The login has expired or was used elsewhere | Log in again. |

## Support

Bug reports and questions: [GitHub issues](https://github.com/lmipsum/plugin.video.simplego/issues).
Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md).

### Reporting a problem

A bug report needs the Kodi log of the problem, with debug logging on:

1. *Settings → System → Logging → Enable debug logging*.
2. Do what goes wrong once more.
3. Take `kodi.log`, or upload it with Kodi's own *Kodi Logfile Uploader* add-on (easiest on a TV box):

   | System | Where `kodi.log` is |
   |---|---|
   | Android | `Android/data/org.xbmc.kodi/files/.kodi/temp/kodi.log` on the device's storage |
   | Windows | `%APPDATA%\Kodi\kodi.log` |
   | Linux | `~/.kodi/temp/kodi.log` |
   | macOS | `~/Library/Logs/kodi.log` |

The add-on's own lines start with `[plugin.video.simplego]`. Before posting, remove tokens and login
addresses (anything with `access_token` or `refresh_token`), account and device identifiers and IP
addresses. Switch debug logging off again afterwards: it makes the log grow fast.

## License

Copyright (C) 2026 lmipsum. Released under the [GNU General Public License v3.0 or later](LICENSE.txt):
you may share and change it, and what you pass on stays under the same licence, with its source.

Telekom and TV GO are trademarks of their respective owners; they are used here only to name the
service the add-on works with.
