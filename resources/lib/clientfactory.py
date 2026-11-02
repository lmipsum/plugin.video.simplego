"""The provider's client the add-on's parts share, and its CA bundle."""

import os
import threading

import xbmc

from resources.lib import kodiutil
from resources.lib import provider

_shared = None
_shared_lock = threading.Lock()
_bundle = None


def make_client():
    """Return a client of its own (it may switch to guest mode, see provider.auth.Auth.guest)."""
    return provider.Client(
        kodiutil.PROFILE,
        # Made at the client's first request (a menu needs none).
        ca_bundle=ca_bundle,
        # The client's measurements (state file, startup page), shown with Kodi's debug logging.
        debug=lambda message: kodiutil.log(message, xbmc.LOGDEBUG),
        # Waiting for the state file's lock, Kodi's exit comes first.
        lock_wait=xbmc.Monitor().waitForAbort,
    )


def has_login():
    """Return whether the add-on is logged in, cheaply (see provider.has_login)."""
    return provider.has_login(kodiutil.PROFILE)


def shared_client():
    """Return one client for the whole process (the service's streams), reusing its connections across switches."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = make_client()
        return _shared


def forget_shared_client():
    """Forget the shared client after a login or logout elsewhere: the next stream starts from the file as it is then."""
    global _shared
    with _shared_lock:
        _shared = None


def ca_bundle():
    """Return the CA bundle's path: certifi's roots plus the certificates player.telekomtvgo.hu fails to send.

    The server omits its Sectigo DV E36 intermediate, and Kodi's certifi (2023.5.7)
    predates the Sectigo E46 root, so E46 cross-signed by USERTrust ECC is shipped too.
    Refreshed by scripts/update_certs.py; tests/test_certs.py warns before expiry.
    """
    global _bundle
    if _bundle:
        return _bundle
    certs_dir = os.path.join(kodiutil.ADDON_PATH, "resources", "certs")
    extras = sorted(os.path.join(certs_dir, f) for f in os.listdir(certs_dir) if f.endswith(".crt"))
    bundle = os.path.join(kodiutil.PROFILE, "ca-bundle.pem")
    sources = [_certifi_file()] + extras
    if not os.path.exists(bundle) or os.path.getmtime(bundle) < max(os.path.getmtime(p) for p in sources):
        os.makedirs(kodiutil.PROFILE, exist_ok=True)
        with open(bundle, "w") as out:
            for p in sources:
                with open(p) as f:
                    out.write(f.read() + "\n")
    _bundle = bundle
    return bundle


def _certifi_file():
    """Return certifi's cacert.pem, found without importing certifi (its import pulls in much more)."""
    import importlib.util

    spec = importlib.util.find_spec("certifi")
    path = os.path.join(os.path.dirname(spec.origin), "cacert.pem") if spec and spec.origin else ""
    if os.path.exists(path):
        return path
    import certifi

    return certifi.where()
