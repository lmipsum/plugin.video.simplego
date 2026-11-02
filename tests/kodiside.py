"""What the Kodi side's tests share: a client with a lock, a channel, its programme, airings."""


class Client:
    """A logged-in account with a parental lock (PIN 1234) and two channels."""

    authed = True
    pin = "1234"

    def __init__(self, lock=True):
        self.lock = lock
        self.pins_checked = []

    def parental_lock_enabled(self):
        return self.lock

    def verify_pin(self, pin):
        self.pins_checked.append(pin)
        return pin == self.pin

    def channel_of(self, channel_id):
        return {"1": {"station_id": "1001"}, "9": {"station_id": "1009", "adult": True}}.get(channel_id)


G = "[COLOR grey]%s[/COLOR]"


CHANNEL = {"id": "C1", "media_id": "M", "number": 1, "name": "M1", "logo": "logo.png", "genres": []}


ON_AIR = {
    "program_id": "AB-1",
    "description": "Sorozat",
    "episode_name": "Első rész",
    "start_time": "2026-10-30T20:00:00Z",
    "end_time": "2026-10-30T20:45:00Z",
    "content_flags": ["ct"],
    "has_audio_description": True,
    "has_sign_language": True,
}


def call(query, handle="1", client=None):
    """A plugin call with this query (and client), as Kodi makes it."""
    from resources.lib.views import call as calls

    return calls.Call(["plugin://plugin.video.simplego/", handle, query], client=client)


def channel_list():
    from resources.lib.views import channels

    return channels.ChannelViews(call("?action=channels"))


def continue_at(monkeypatch, tmp_path, now="2026-10-29T12:00:00Z"):
    """Keep Continue watching's rows in tmp_path, at a fixed time (the positions' programmes stay on catch-up)."""
    import types

    from resources.lib.data import continuelist
    from resources.lib.util import isotime

    monkeypatch.setattr(continuelist, "KEPT", str(tmp_path / "continue.json"))
    monkeypatch.setattr(continuelist, "time", types.SimpleNamespace(time=lambda: isotime.stamp(now)))
    return continuelist


OLD = {"start_utc": "2026-10-27T21:30:00Z", "end_utc": "2026-10-27T23:45:00Z", "station_id": "1", "entitlements": ["ct"]}


NEWER = dict(OLD, start_utc="2026-10-29T21:30:00Z", end_utc="2026-10-29T23:45:00Z")


COMING = dict(OLD, start_utc="2099-01-01T20:00:00Z", end_utc="2099-01-01T22:00:00Z")
