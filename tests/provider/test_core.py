"""The provider's web API core: the refresh token in pasted text, the account header, token expiry, network failures."""

import base64
import json

import pytest

from resources.lib import provider
from resources.lib.provider import core
from resources.lib.provider import statefile

# A JWT-shaped placeholder, not a real token.
TOKEN = "aaaa.bbbb.cccc"
EXPIRY = 1824576516


@pytest.mark.parametrize(
    "text",
    [
        TOKEN,
        "  %s \n" % TOKEN,
        '"%s"' % TOKEN,
        "https://player.example/robots.txt?oauth=x&access_token=AAA&refresh_token=%s&expires_in=5#frag" % TOKEN,
    ],
)
def test_extract_refresh_token(text):
    assert core.extract_refresh_token(text) == TOKEN


@pytest.mark.parametrize("text", ["", None, "hello", "User-agent: *\nDisallow: /", "refresh_token=nodots"])
def test_extract_refresh_token_rejects_text_without_one(text):
    assert core.extract_refresh_token(text) == ""


def test_account_details_header():
    acc = {
        "account_type": "TYPE",
        "user_id": "1",
        "is_recording_enabled": False,
        "channelMap_id": "2",
        "rightsGroup_ids": "3,4",
        "release_slot": "5",
        "account_id": "1",
        "managed_settings": {"TVSOA-setting-VodEnabled": "true"},
    }
    header = core.account_details(acc)
    assert header == (
        '{"accountType":"TYPE","userId":"1","recordingEnabledDVR":false,"channelMapId":"2",'
        '"rightsGroupIds":"3,4","releaseSlot":"5","accountId":"1","vodEnabled":"true"}'
    )


def test_a_network_failure_is_an_api_error(tmp_path):
    with pytest.raises(provider.ApiError):
        core.Api(statefile.State(str(tmp_path / core.STATE_FILE))).http.get("http://127.0.0.1:1/", timeout=5)


def test_a_tokens_expiry_is_read_from_its_payload():
    payload = base64.urlsafe_b64encode(json.dumps({"exp": EXPIRY, "typ": "Refresh"}).encode()).decode().rstrip("=")
    assert core.token_expiry("aaaa.%s.cccc" % payload) == EXPIRY


@pytest.mark.parametrize("text", ["not a jwt", None])
def test_a_text_without_a_token_has_no_expiry(text):
    assert core.token_expiry(text) is None
