"""When a live stream is opened again before its window ends: just after a programme starts, if one does in time."""

from resources.lib.stream import windowrenewal

HOUR = 3600
LIVE = 20  # seconds behind the edge: watching live


def _renewal(programme_start, asked=None):
    def start(when):
        if asked is not None:
            asked.append(when)
        return programme_start

    return windowrenewal.WindowRenewal(window_end=6 * HOUR, programme_start=start)


def test_it_is_due_just_after_the_last_programme_start_before_the_window_ends():
    asked = []
    renewal = _renewal(programme_start=4 * HOUR, asked=asked)
    after_start = 4 * HOUR + windowrenewal.START_SLACK
    assert not renewal.is_due(after_start - 1, LIVE)
    assert renewal.is_due(after_start, LIVE)
    assert asked == [6 * HOUR - windowrenewal.END_MARGIN]  # the guide asked once, for the deadline


def test_watching_back_it_waits_for_the_deadline():
    renewal = _renewal(programme_start=4 * HOUR)
    behind = windowrenewal.WATCHING_BACK + 1
    assert not renewal.is_due(5 * HOUR, behind)
    assert renewal.is_due(renewal.deadline, behind)


def test_without_a_programme_start_ahead_it_is_due_at_the_deadline():
    started_before = _renewal(programme_start=-HOUR)  # one programme over the whole window
    unknown = _renewal(programme_start=None)
    too_late = _renewal(programme_start=6 * HOUR - windowrenewal.END_MARGIN)  # its slack past the deadline
    for renewal in (started_before, unknown, too_late):
        assert not renewal.is_due(renewal.deadline - 1, LIVE)
        assert renewal.is_due(renewal.deadline, LIVE)
