"""The programme on air, asked once per channel start."""


def test_a_channel_start_reads_the_programme_once(monkeypatch):
    from resources.lib.data import onair

    asked = []

    class Client:
        def programme_at(self, station, when, cache_dir):
            asked.append((station, when))
            return {"title": "Híradó"}, when + 600

    monkeypatch.setattr(onair, "_recent", {})
    for _ in range(3):  # the parental gate, the details, the position
        assert onair.on_air(Client(), "18718", 1000)[0] == {"title": "Híradó"}
    assert asked == [("18718", 1000)]
    onair.on_air(Client(), "18719", 1000)
    assert len(asked) == 2  # another channel: asked
