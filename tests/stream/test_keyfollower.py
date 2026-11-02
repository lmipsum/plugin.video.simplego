import time

from resources.lib.stream import keyfollower


class Proxy:
    """A stream's proxy with one key change 399 s into the stream."""

    def __init__(self, part=0, changes=(399.0,)):
        self.part = part
        self.change_times = changes
        self.found_changes = [[99]]
        self.prefetched = self.stopped = False

    def part_of(self, seconds):
        return sum(1 for t in self.change_times if seconds >= t)

    def prefetch(self):
        self.prefetched = True

    def stop(self):
        self.stopped = True


class Clock:
    """The test's time: moves only when told to."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Player:
    """Plays on from `position` as the clock moves (real time if none), or stands still when paused."""

    def __init__(self, position, paused=False, clock=time.time):
        self.clock, self.position, self.paused = clock, position, paused
        self.start = clock()

    def getTime(self):
        return self.position + (0 if self.paused else self.clock() - self.start)


class Timers:
    """threading.Timer stood in for: what is timed waits until the test fires it."""

    def __init__(self, clock):
        self.clock, self.pending = clock, []

    def __call__(self, delay, function, args=()):
        timers = self

        class Timer:
            daemon = False

            def start(self):
                timers.pending.append((delay, function, args))

            def cancel(self):
                pass

        return Timer()

    def fire(self):
        """Let the next timed call's delay pass, then run it; return its delay."""
        delay, function, args = self.pending.pop(0)
        self.clock.now += delay
        function(*args)
        return delay


def follower(proxy=None, known=None):
    made = []

    def make_proxy(part):
        made.append(Proxy(part))
        return made[-1]

    follower = keyfollower.KeyFollower(proxy or Proxy(), make_proxy, known=known, key=("channel", "start"))
    restarts = []
    follower.restart = lambda part, seconds: restarts.append((part, round(seconds, 1), time.time()))
    return follower, made, restarts


def test_the_restart_is_timed_half_a_second_before_the_key_change(kodi, monkeypatch):
    clock = Clock()
    timers = Timers(clock)
    monkeypatch.setattr(keyfollower.threading, "Timer", timers)
    keys, _, restarts = follower()
    player = Player(397.8, clock=clock)
    keys.follow(397.8, player)
    assert round(timers.fire(), 1) == 0.7  # 1.2 s to the change at 399, less half a second
    # Just before the change, on its first segment (InputStream Adaptive goes on from
    # the first segment after the position asked for).
    assert [(part, target) for part, target, _ in restarts] == [(1, 398.7)]
    assert timers.pending == []


def test_a_paused_player_is_not_restarted_before_it_reaches_the_change(kodi, monkeypatch):
    clock = Clock()
    timers = Timers(clock)
    monkeypatch.setattr(keyfollower.threading, "Timer", timers)
    keys, _, restarts = follower()
    keys.follow(397.8, Player(397.8, paused=True, clock=clock))
    timers.fire()
    timers.fire()
    # Still 1.2 s before the change each time: timed again, not restarted.
    assert restarts == [] and len(timers.pending) == 1
    keys.close()


def test_a_jump_into_the_next_key_part_restarts_right_there(kodi):
    keys, _, restarts = follower()
    keys.follow(450.0, Player(450.0))
    assert [(part, target) for part, target, _ in restarts] == [(1, 450.0)]


def test_the_next_part_is_made_ready_twenty_seconds_ahead(kodi):
    keys, made, _ = follower()
    keys.follow(370.0, Player(370.0))
    assert made == []
    keys.follow(385.0, Player(385.0))
    assert len(made) == 1 and made[0].part == 1 and made[0].prefetched
    assert keys.part_proxy(1) is made[0]  # the restart takes the one made ready


def test_switching_parts_stops_the_old_proxy_once_the_new_one_plays(kodi):
    old = Proxy()
    keys, _, _ = follower(old)
    new = Proxy(part=1)
    keys.switch(new)
    assert keys.proxy is new and keys.switching and not old.stopped
    keys.switched()
    assert old.stopped and not keys.switching


def test_the_key_changes_found_are_kept_for_the_next_stream_of_the_programme(kodi):
    known = {}
    keys, _, _ = follower(known=known)
    keys.follow(10.0, Player(10.0))
    assert known == {("channel", "start"): [[99]]}


def test_a_stream_without_key_changes_is_left_alone(kodi, monkeypatch):
    timers = Timers(Clock())
    monkeypatch.setattr(keyfollower.threading, "Timer", timers)
    keys, made, restarts = follower(Proxy(changes=()))
    keys.follow(398.0, Player(398.0))
    assert made == [] and restarts == [] and timers.pending == []


class LiveProxy(Proxy):
    """A live stream's proxy that noticed a key change 6 s before the edge, at the clock's 1000."""

    def __init__(self):
        super().__init__(changes=())
        self.live_changes = ((1000.0, 6.0, "video", "old", "new"),)


class LivePlayer(Player):
    """A live stream's player `behind` seconds behind the edge (Kodi's total time is the edge)."""

    def __init__(self, behind, clock, paused=False):
        super().__init__(100.0, paused=paused, clock=clock)
        self.behind = behind

    def getTotalTime(self):
        return self.position + self.behind + (self.clock() - self.start)


def test_a_live_key_change_restarts_the_stream_when_the_player_gets_there(kodi, monkeypatch):
    clock = Clock()
    timers = Timers(clock)
    monkeypatch.setattr(keyfollower.threading, "Timer", timers)
    monkeypatch.setattr(keyfollower.time, "time", clock)
    keys, _, restarts = follower(LiveProxy())
    restarts_at = []
    keys.restart = lambda part, seconds: restarts_at.append((part, seconds, clock.now))
    clock.now = 1002.0  # noticed 2 s ago: the change is 8 s behind the edge now
    keys.follow(0, LivePlayer(20.0, clock), now=clock.now)
    # 20 s behind the edge: 12 s until the player reaches it, and the moment after.
    assert timers.fire() == 13.0
    assert restarts_at == [(0, None, 1015.0)]  # live: from its edge, no start offset
    keys.follow(0, LivePlayer(20.0, clock), now=clock.now)
    assert timers.pending == []  # once


def test_a_paused_live_player_is_restarted_only_once_it_reaches_the_change(kodi, monkeypatch):
    clock = Clock()
    timers = Timers(clock)
    monkeypatch.setattr(keyfollower.threading, "Timer", timers)
    monkeypatch.setattr(keyfollower.time, "time", clock)
    keys, _, _ = follower(LiveProxy())
    restarts_at = []
    keys.restart = lambda part, seconds: restarts_at.append(clock.now)
    player = LivePlayer(20.0, clock)
    keys.follow(0, player, now=clock.now)
    player.paused, player.position = True, player.getTime()  # paused now: the edge moves on, the player not
    timers.fire()
    assert restarts_at == [] and len(timers.pending) == 1


def test_without_kodis_times_the_player_is_taken_to_be_the_default_delay_behind(kodi, monkeypatch):
    class Silent:
        def getTotalTime(self):
            raise RuntimeError("not playing")

    timers = Timers(Clock())
    monkeypatch.setattr(keyfollower.threading, "Timer", timers)
    keys, _, _ = follower(LiveProxy())
    keys.follow(0, Silent(), now=1000.0)
    assert timers.pending[0][0] == keyfollower.LIVE_LAG - 6.0 + keyfollower.LIVE_RESTART_AFTER
