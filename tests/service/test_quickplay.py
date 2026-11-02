"""The fast play path's messages."""

from resources.lib import provider


def test_every_provider_error_kind_has_a_message():
    from resources.lib.service import quickplay

    kinds = {cls.kind for cls in provider.ApiError.__subclasses__()}
    assert None not in kinds and kinds - set(quickplay.SILENT) <= set(quickplay.ERRORS)


def test_only_a_live_play_marks_its_channel():
    from resources.lib.service import quickplay

    assert quickplay.playing_mark({"id": "C1", "media": "M"}) == "C1"
    # Watched back or restarted from its beginning: no live channel to mark (and an earlier mark goes).
    assert quickplay.playing_mark({"id": "C1", "media": "M", "programme": "2026-10-28T20:00:00Z~..."}) == ""


def test_an_expired_airing_offers_its_programme_onto_the_favourites(kodi):
    from resources.lib.service import quickplay

    offer = {"id": "S1", "kind": "series", "title": "Doktor Balaton", "next": "2099.11.05. 20:00, Mozi+ HD"}
    quickplay.offer_instead("plugin://plugin.video.simplego/", "Gone.", offer)  # answered no
    assert not [m for m, kind in kodi.LOG if kind == "builtin"]
    kodi.ANSWERS["yesno"] = True
    quickplay.offer_instead("plugin://plugin.video.simplego/", "Gone.", offer)
    ((added, _),) = [(m, kind) for m, kind in kodi.LOG if kind == "builtin"]
    assert added == "RunPlugin(plugin://plugin.video.simplego/?action=watch&id=S1&kind=series&on=1)"


def test_an_expired_airing_with_nothing_to_come_offers_its_row_off_continue_watching(kodi):
    from resources.lib.service import quickplay

    kodi.ANSWERS["yesno"] = True
    quickplay.offer_instead("plugin://plugin.video.simplego/", "Gone.", {"mark": "1246_A_B"})
    ((removed, _),) = [(m, kind) for m, kind in kodi.LOG if kind == "builtin"]
    assert removed == "RunPlugin(plugin://plugin.video.simplego/?action=continue_remove&mark=1246_A_B)"


def test_an_expired_catch_up_has_a_message_of_its_own():
    from resources.lib.service import quickplay

    assert provider.errors.CatchupExpiredError.kind in quickplay.ERRORS
