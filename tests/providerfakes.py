"""Stand-ins for what the provider's parts are given: the API, the login, the AMP gateway, the STS."""

import json
import time
import types


class Answer:
    """An HTTP response: its status, text and JSON."""

    def __init__(self, status=200, data=None, text="", headers=None):
        self.status_code, self.ok = status, status < 400
        self.text = text or json.dumps(data or {})
        self.content = self.text.encode()
        self.headers = headers or {}
        self._data = data or {}

    def json(self):
        return self._data


class FakeAuth:
    """A login: calls answered by answer(path, params), what was asked kept.

    :param answer: answer(path, params) gives a call's JSON; what it raises, the call raises
    :param authed: logged in (the account's lists) or a guest (the public ones)
    """

    def __init__(self, answer=None, authed=True):
        self.authed = authed
        self.calls = []  # (path, method, params, body)
        self.tokens = []  # how far ahead each valid token was asked for
        self._answer = answer or (lambda path, params: {})
        self._readded = []

    def call(self, path, flow, step=None, params=None, method="GET", body=None, readd=True):
        self.calls.append((path, method, params, body))
        return self._answer(path, params or {})

    def call_as_account(self, path, flow, step=None, params=None):
        return self.call(path, flow, step, params)

    def valid_access_token(self, ahead=None):
        self.tokens.append(ahead)
        return "t"

    def valid_account(self, force=False, fresh_login=False):
        return {}

    def channel_map(self):
        return ""

    def on_device_readded(self, forget):
        self._readded.append(forget)

    def readd_device(self):
        for forget in self._readded:
            forget()


class FakeApi:
    """The web API without the web: a startup page that is always fresh, and this HTTP session.

    :param state: the state the startup page's time goes into
    :param http: the HTTP session (see AmpHttp, StsHttp)
    :param answers: the bifrost responses send() gives, in turn
    :param guest: guest(path, params) gives a guest call's JSON
    """

    def __init__(self, state=None, http=None, answers=(), guest=None):
        self.http = http
        self.bootstraps = []
        self.sent = []  # (path, params)
        self._state = state
        self._answers = list(answers)
        self._guest = guest or (lambda path, params: {})

    def bootstrap(self, force=False):
        self.bootstraps.append(force)
        if self._state is not None:
            self._state["config_at"] = time.time()

    def send(self, path, flow, step=None, params=None, method="GET", body=None, token=None, account=None):
        self.sent.append((path, params))
        return self._answers.pop(0)

    def call(self, path, flow, step=None, params=None, method="GET", body=None):
        return self._guest(path, params or {})


class AmpHttp:
    """The AMP gateway: a roll answered by roll(body) (its response, or an error code), registrations taken.

    The licence server gives no service certificate.
    """

    def __init__(self, roll=None):
        self.rolls = []  # the roll bodies asked for
        self.registrations = []  # the channel each registration was made for
        self._roll = roll or (lambda body: {})

    def post(self, url, params=None, data=None, headers=None, timeout=None):
        if "get-widevine-license" in url:
            return Answer(500)
        if url.endswith("/v1/client/registrations"):
            self.registrations.append(headers["ApplicationToken"])
            return Answer(data={"result": "success", "response": {}})
        body = json.loads(data)
        self.rolls.append(body["roll"])
        answer = self._roll(body)
        if isinstance(answer, int):  # an AMP error code
            return Answer(469, {"result": "error", "response": {"code": answer, "message": "refused"}})
        return Answer(data={"result": "success", "response": answer})


class StsHttp:
    """The STS: a refresh token traded for a new access token at once (one redirect)."""

    def __init__(self):
        self.renewals = 0

    def get(self, url, allow_redirects=True, timeout=None):
        self.renewals += 1
        return Answer(302, headers={"Location": "https://player.telekomtvgo.hu/#access_token=new&expires_in=3600"})


# A channel list known to the playback: subscribed_ids() as given.
def subscription(ids):
    return types.SimpleNamespace(subscribed_ids=lambda fetch=True: ids)
