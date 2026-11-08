"""Opening a live stream again before its window ends, where the guide has a programme start.

A live window has an end (see provider.playback): past it the manifest stops growing and the player
waits for segments that never come. The stream is opened again before then, preferably just after a
programme starts, where adverts and trailers mostly run: the last such moment before the window ends.
"""

# Opened again at the latest this long before the window ends: time for the new stream to start.
END_MARGIN = 5 * 60
# Past a programme's start in the guide: programmes often start a little late.
START_SLACK = 60
# A viewer further behind the live edge than this is watching back: opened again, the stream would
# jump to the edge, so that waits for the deadline.
WATCHING_BACK = 60


class WindowRenewal:
    """When to open a live stream with a window end again.

    :param window_end: when the stream's window ends (a timestamp)
    :param programme_start: programme_start(when) returns the start (a timestamp) of the programme on
        at `when`, None if unknown; asked once, at the first is_due
    """

    def __init__(self, window_end, programme_start):
        self.deadline = window_end - END_MARGIN
        self._programme_start = programme_start
        self._renew_at = None

    def is_due(self, now, behind_live):
        """Return whether to open the stream again now.

        :param behind_live: how far (seconds) the player is behind the live edge
        """
        if now >= self.deadline:
            return True
        if self._renew_at is None:
            self._renew_at = self._choose_renewal_time(now)
        return now >= self._renew_at and behind_live <= WATCHING_BACK

    def _choose_renewal_time(self, now):
        """Return when the last programme on before the deadline has just started; the deadline if none is ahead."""
        start = self._programme_start(self.deadline)
        if start is not None and now < start + START_SLACK <= self.deadline:
            return start + START_SLACK
        return self.deadline
