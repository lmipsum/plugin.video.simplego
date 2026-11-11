"""Where the add-on runs: telling a phone or tablet (it can open links itself) from a TV."""

import subprocess

import pytest

from resources.lib.util import kodienv


def _getprop(monkeypatch, answer):
    """Make getprop answer ro.build.characteristics so, or raise if the answer is an exception."""
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if isinstance(answer, BaseException):
            raise answer
        return subprocess.CompletedProcess(command, 0, stdout=answer + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)  # imported where used
    return calls


@pytest.mark.parametrize(
    ("characteristics", "expected"), [("phone", True), ("tablet", True), ("default", True), ("tv,nosdcard", False), ("tv", False)]
)
def test_an_android_tv_build_is_no_phone(kodi, monkeypatch, characteristics, expected):
    calls = _getprop(monkeypatch, characteristics)
    assert kodienv.phone_or_tablet() is expected
    assert calls == [["getprop", "ro.build.characteristics"]]


@pytest.mark.parametrize("failure", [OSError("no getprop"), subprocess.TimeoutExpired("getprop", 2)])
def test_unsure_counts_as_a_phone(kodi, monkeypatch, failure):
    _getprop(monkeypatch, failure)
    assert kodienv.phone_or_tablet() is True  # a dead link on a TV costs nothing, a missing one strands a phone


@pytest.mark.parametrize(("android", "expected"), [(True, False), (False, True)])
def test_only_android_widevine_is_trusted(kodi, android, expected):
    kodi.CONDITIONS["System.Platform.Android"] = android
    assert kodienv.untrusted_widevine() is expected


def test_off_android_nothing_is_asked(kodi, monkeypatch):
    kodi.CONDITIONS["System.Platform.Android"] = False
    calls = _getprop(monkeypatch, "phone")
    assert kodienv.phone_or_tablet() is False
    assert calls == []
