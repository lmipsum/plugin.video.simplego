"""Each plugin action's view, whether it lists a folder, and where it is in the menu."""

import os
import re

from resources.lib import kodiutil
from resources.lib.views import routes


def test_every_settings_button_runs_an_action_of_the_plugin():
    with open(os.path.join(kodiutil.ADDON_PATH, "resources", "settings.xml"), encoding="utf-8") as f:
        actions = re.findall(r"RunPlugin\(plugin://plugin\.video\.simplego/\?action=(\w+)", f.read())
    assert "tv_refresh" in actions
    assert [a for a in actions if a not in routes.ROUTES] == []


def test_every_route_names_a_view_class_with_its_action():
    import importlib

    for action, route in routes.ROUTES.items():
        view = getattr(importlib.import_module("resources.lib.views." + route.module), route.view)
        assert callable(getattr(view, "do_" + action))


def test_each_list_names_where_it_is_in_the_menu():
    """Kodi's breadcrumb (top left) shows the plugin category; without one, only "Videos"."""

    def category(action):
        return routes.ROUTES[action].category

    assert category("channels") == (30001,)
    assert category("mychannels") == (30175,)
    assert category("watchlist") == category("seasons") == (30168,)
    assert category("continue") == (30188,)
    assert category("root") == ()


def test_only_the_lists_end_as_a_listing():
    listings = [action for action in routes.ROUTES if routes.is_listing(action)]
    assert listings == ["root", "channels", "mychannels", "watchlist", "seasons", "continue"]
    assert not routes.is_listing("play") and not routes.is_listing("unknown")
