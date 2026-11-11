"""The fast play path."""


def test_only_a_live_play_marks_its_channel():
    from resources.lib.service import quickplay

    assert quickplay.playing_mark({"id": "C1", "media": "M"}) == "C1"
    # Watched back or restarted from its beginning: no live channel to mark (and an earlier mark goes).
    assert quickplay.playing_mark({"id": "C1", "media": "M", "programme": "2026-10-28T20:00:00Z~..."}) == ""
