"""One holder at a time of a Home window property, across Kodi's add-on processes."""

import time

from resources.lib.util import homelock


class _Home:
    """Kodi's Home window: properties every process shares."""

    def __init__(self):
        self.properties = {}

    def getProperty(self, name):
        return self.properties.get(name, "")

    def setProperty(self, name, value):
        self.properties[name] = value

    def clearProperty(self, name):
        self.properties.pop(name, None)


def test_a_taken_lock_is_held_until_its_holder_releases_it():
    home = _Home()
    first, second = homelock.HomeLock(home, "busy", 30), homelock.HomeLock(home, "busy", 30)
    assert not first.held() and not first.is_mine()
    first.take()
    assert second.held() and first.is_mine() and not second.is_mine()
    second.release()  # not its mark: it stays
    assert first.held()
    first.release()
    assert not second.held() and home.properties == {}


def test_of_two_taking_it_at_once_the_last_ones_mark_stays():
    home = _Home()
    first, second = homelock.HomeLock(home, "busy", 30), homelock.HomeLock(home, "busy", 30)
    first.take()
    second.take()
    assert second.is_mine() and not first.is_mine()


def test_a_stale_mark_holds_nothing():
    home = _Home()
    home.setProperty("busy", "%f 1-1" % (time.time() - 60))  # a crashed holder's
    lock = homelock.HomeLock(home, "busy", 30)
    assert not lock.held()
    home.setProperty("busy", str(time.time()))  # a mark of the time alone
    assert lock.held()
