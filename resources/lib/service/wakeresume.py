"""Playing the live channel again that was on when Kodi went to sleep (the TV off), once it wakes up.

On waking Kodi resumes what was watched back but never a live channel, so that is played again here.
"""

import threading
import time

# Going to sleep, Kodi stops playing a moment before or after it says so: a live channel
# stopped this recently counts as playing. On waking, it plays again after Kodi's own resume jobs.
SLEEP_STOP = 30
WAKE_DELAY = 5


class WakeResume:
    """Follow which live channel plays, and play it again on waking up if it played when Kodi went to sleep.

    :param play_live: play_live(channel, why) opens a live channel's stream and plays it
    :param is_playing: is_playing() returns whether Kodi plays anything
    """

    def __init__(self, play_live, is_playing):
        self._play_live = play_live
        self._is_playing = is_playing
        # Set from Kodi's player callbacks, read from its monitor's.
        self._lock = threading.Lock()
        self._live = None  # (channel, when it stopped or None while it plays): the last live channel
        self._resume = None  # the live channel to play again on waking up

    def playing(self, channel):
        """Note what plays now: a live channel of ours, or None for anything else."""
        with self._lock:
            self._live = (channel, None) if channel else None

    def stopped(self):
        """Note that what played stopped: a live channel playing until now stopped now."""
        with self._lock:
            if self._live and self._live[1] is None:
                self._live = (self._live[0], time.time())

    def on_power(self, method):
        """Handle System.OnSleep / System.OnWake (the TV off and on)."""
        if method == "System.OnSleep":
            with self._lock:
                live = self._live
            recent = live and (live[1] is None or time.time() - live[1] < SLEEP_STOP)
            self._resume = live[0] if recent else None
        elif method == "System.OnWake" and self._resume:
            channel, self._resume = self._resume, None
            timer = threading.Timer(WAKE_DELAY, self._play_again, (channel,))
            timer.daemon = True
            timer.start()

    def _play_again(self, channel):
        """Play the live channel again, unless something plays already."""
        if self._is_playing():
            return
        self._play_live(channel, "after waking up")
