"""Stand-ins for Kodi's Python modules (xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs).

Just enough of them for the add-on's Kodi side to import and run its logic in a
test: settings and Home window properties live in dicts, strings come from the
add-on's own English strings.po, dialogs answer what a test put in ANSWERS, and
JSON-RPC calls answer from JSONRPC.
"""

import json
import os
import re
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Each test gets a profile folder of its own (see conftest); this one is never created.
PROFILE = os.path.join(tempfile.gettempdir(), "simplego-profile-unset")

LOG = []  # (message, level)
SETTINGS = {}
# The settings' defaults (resources/settings.xml), as Kodi gives an unset setting.
_DEFAULTS = dict(
    re.findall(
        r'<setting id="([^"]+)"[^>]*>(?:(?!</setting>).)*?<default>([^<]*)</default>',
        open(os.path.join(os.path.dirname(__file__), "..", "resources", "settings.xml"), encoding="utf-8").read(),
        re.S,
    )
)
PROPERTIES = {}
CONDITIONS = {}  # Kodi condition -> bool
# The add-on runs on Android only, with inputstream.adaptive: a test off them says so.
PLATFORM = {"System.Platform.Android": True, "System.AddonIsEnabled(inputstream.adaptive)": True}
JSONRPC = {}  # method -> result, or a function(params) giving it
ANSWERS = {}  # dialog method -> its answer, or a list of answers taken in turn


def _strings():
    path = os.path.join(ROOT, "resources", "language", "resource.language.en_gb", "strings.po")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return {int(n): s for n, s in re.findall(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"', text)}


STRINGS = _strings()


def answer(method, default=None):
    value = ANSWERS.get(method, default)
    if isinstance(value, list):
        return value.pop(0) if value else default
    return value


def reset():
    """Forget what an earlier test set."""
    for store in (LOG, SETTINGS, PROPERTIES, CONDITIONS, JSONRPC, ANSWERS):
        store.clear()
    CONDITIONS.update(PLATFORM)


# ---------------------------------------------------------------- xbmc
xbmc = types.ModuleType("xbmc")
xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 0, 1, 2, 3
xbmc.ISO_639_1, xbmc.ISO_639_2 = 0, 1
xbmc.log = lambda msg, level=1: LOG.append((msg, level))
xbmc.getCondVisibility = lambda condition: CONDITIONS.get(condition, False)
xbmc.getGlobalIdleTime = lambda: 0  # a key was just pressed
xbmc.getInfoLabel = lambda label: {"System.BuildVersion": "21.2 (21.2.0)"}.get(label, "")
xbmc.getRegion = lambda what: {"dateshort": "%Y-%m-%d", "time": "%H:%M:%S"}.get(what, "")
xbmc.getLanguage = lambda form=None: "hun"
xbmc.getLocalizedString = lambda string_id: {
    19031: "Next",
    12021: "Play from beginning",
    14076: "Add to favourites",
    14077: "Remove from favourites",
    10005: "Not available",
    20343: "TV shows",
}.get(string_id, "")  # Kodi's own strings
xbmc.convertLanguage = lambda value, form=None: value
xbmc.VideoStreamDetail = lambda **details: details  # what a row's stream is said to be
xbmc.Actor = lambda name="", role="", order=-1, thumbnail="": name  # a cast member, by name
xbmc.getIPAddress = lambda: "127.0.0.1"
xbmc.executebuiltin = lambda command, wait=False: LOG.append((command, "builtin"))


def _jsonrpc(request):
    call = json.loads(request)
    result = JSONRPC.get(call["method"])
    if callable(result):
        result = result(call.get("params") or {})
    if result is None:
        return json.dumps({"id": 1, "jsonrpc": "2.0", "error": {"code": -32601}})
    return json.dumps({"id": 1, "jsonrpc": "2.0", "result": result})


xbmc.executeJSONRPC = _jsonrpc


class Monitor:
    def abortRequested(self):
        return False

    def waitForAbort(self, timeout=None):
        return False


class Player:
    def __init__(self, *args):
        pass

    def isPlaying(self):
        return False


xbmc.Monitor, xbmc.Player = Monitor, Player

# ---------------------------------------------------------------- xbmcaddon
xbmcaddon = types.ModuleType("xbmcaddon")


class Addon:
    INFO = {"id": "plugin.video.simplego", "name": "Simple GO", "profile": PROFILE, "path": ROOT}

    def __init__(self, addon_id=None):
        pass

    def getAddonInfo(self, key):
        return self.INFO.get(key, "")

    def getLocalizedString(self, string_id):
        return STRINGS.get(string_id, "")

    def getSetting(self, key):
        return str(SETTINGS.get(key, _DEFAULTS.get(key, "")))

    def getSettingBool(self, key):
        return bool(SETTINGS.get(key, _DEFAULTS.get(key) == "true"))

    def getSettingInt(self, key):
        return int(SETTINGS.get(key, _DEFAULTS.get(key) or 0))

    def setSetting(self, key, value):
        SETTINGS[key] = value

    setSettingBool = setSettingInt = setSetting


xbmcaddon.Addon = Addon

# ---------------------------------------------------------------- xbmcgui
xbmcgui = types.ModuleType("xbmcgui")
xbmcgui.NOTIFICATION_INFO, xbmcgui.NOTIFICATION_WARNING, xbmcgui.NOTIFICATION_ERROR = "info", "warning", "error"
xbmcgui.INPUT_ALPHANUM, xbmcgui.INPUT_NUMERIC = 0, 1


class Window:
    def __init__(self, window_id=None):
        pass

    def getProperty(self, key):
        return PROPERTIES.get(key, "")

    def setProperty(self, key, value):
        PROPERTIES[key] = value

    def clearProperty(self, key):
        PROPERTIES.pop(key, None)


class Dialog:
    def ok(self, heading, message):
        LOG.append((message, "ok"))
        return True

    def notification(self, heading, message, icon=None, time=5000, sound=True):
        LOG.append((message, "notification"))

    def numeric(self, kind, heading, default="", hidden=False):
        return answer("numeric", "")

    def input(self, heading, defaultt="", type=0, option=0, autoclose=0):
        LOG.append((heading, "input"))
        return answer("input", "")

    def yesno(self, heading, message, nolabel="", yeslabel="", **kwargs):
        return answer("yesno", False)

    def select(self, heading, options, **kwargs):
        return answer("select", -1)

    def contextmenu(self, options):
        return answer("contextmenu", -1)


class _Item:
    def __init__(self, *args, **kwargs):
        self.properties = {}
        self.label = args[0] if args else kwargs.get("label", "")
        self.label2 = ""

    def setLabel2(self, label):
        self.label2 = label

    def setProperty(self, key, value):
        self.properties[key] = value

    def getVideoInfoTag(self):
        return self.__dict__.setdefault("tag", _Tag())

    def setArt(self, art):
        self.__dict__.setdefault("art", {}).update(art)

    def select(self, selected):
        self.selected = selected

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _Tag(dict):
    """A video info tag: what each setter was given, by its name without "set" ("Title", "Plot")."""

    def __getattr__(self, name):
        # One value as it is; several (setResumePoint's time and total) as a tuple.
        return lambda *values: self.__setitem__(name[3:], values[0] if len(values) == 1 else values)


xbmcgui.Window, xbmcgui.Dialog = Window, Dialog
xbmcgui.ListItem = xbmcgui.DialogProgress = xbmcgui.DialogProgressBG = _Item
xbmcgui.WindowDialog = xbmcgui.ControlImage = xbmcgui.ControlLabel = xbmcgui.ControlTextBox = _Item

# ---------------------------------------------------------------- xbmcplugin, xbmcvfs
xbmcplugin = types.ModuleType("xbmcplugin")
xbmcplugin.__getattr__ = lambda name: lambda *args, **kwargs: None

xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda path: path.replace("special://profile/", PROFILE + os.sep)


def install():
    for module in (xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs):
        sys.modules.setdefault(module.__name__, module)
