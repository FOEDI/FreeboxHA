"""Transport contracts from the official Freebox OS documentation."""

import hashlib
import hmac
import ssl

import pytest

from custom_components.freebox_ultra_ultimate.api import (
    ApiVersion,
    AuthenticationError,
    EndpointUnavailable,
    FreeboxError,
    PermissionDenied,
    normalize_host,
    tls_context,
)
from custom_components.freebox_ultra_ultimate.auth import challenge_password
from tests.http_mock import HttpMock as aioresponses

META = {
    "uid": "test-box",
    "api_version": "12.7",
    "api_base_url": "/api/",
    "api_domain": "example.fbxos.fr",
    "https_available": True,
}


def test_challenge_password():
    assert challenge_password("token", "challenge") == hmac.new(b"token", b"challenge", hashlib.sha1).hexdigest()


def test_tls_roots_and_hostname_validation():
    context = tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    names = str([cert["subject"] for cert in context.get_ca_certs()])
    assert "Freebox ECC Root CA" in names and "Freebox Root CA" in names


@pytest.mark.parametrize("version", ["", "latest", "0.0", "1", "1.1.1", "-1.2"])
def test_invalid_version(version):
    with pytest.raises(FreeboxError):
        ApiVersion.parse({**META, "api_version": version})


def test_new_major_is_discovered_dynamically():
    assert ApiVersion.parse(META).base_path == "/api/v12/"


@pytest.mark.parametrize(
    "host", ["http://host", "https://user:pass@host", "https://host/api/", "https://host?password=x"]
)
def test_reject_unsafe_host(host):
    with pytest.raises(FreeboxError):
        normalize_host(host)


async def test_discovery_verifies_same_uid(client):
    with aioresponses() as mock:
        mock.get("http://192.0.2.254/api_version", payload=META)
        mock.get("https://192.0.2.254/api_version", payload=META)
        assert (await client.discover()).uid == "test-box"


async def test_discovery_rejects_different_box(client):
    with aioresponses() as mock:
        mock.get("http://192.0.2.254/api_version", payload=META)
        mock.get("https://192.0.2.254/api_version", payload={**META, "uid": "other"})
        with pytest.raises(FreeboxError, match="wrong_freebox"):
            await client.discover()


async def test_authorization_and_login(client):
    with aioresponses() as mock:
        mock.post(
            "https://192.0.2.254/api/v12/login/authorize/",
            payload={"success": True, "result": {"app_token": "new-token", "track_id": 42}},
        )
        assert await client.authorize("test.app") == ("new-token", 42)
        mock.get(
            "https://192.0.2.254/api/v12/login/authorize/42", payload={"success": True, "result": {"status": "granted"}}
        )
        assert await client.authorization_status(42) == "granted"
        mock.get("https://192.0.2.254/api/v12/login/", payload={"success": True, "result": {"challenge": "test"}})
        mock.post(
            "https://192.0.2.254/api/v12/login/session/",
            payload={"success": True, "result": {"session_token": "session", "permissions": {"downloader": True}}},
        )
        await client.login()
        assert client.permissions == {"downloader": True}


@pytest.mark.parametrize(
    ("code", "status", "error"),
    [
        ("insufficient_rights", 403, PermissionDenied),
        ("not_found", 404, EndpointUnavailable),
        ("invalid_token", 403, AuthenticationError),
        ("busy", 503, FreeboxError),
    ],
)
async def test_errors_are_typed_and_redacted(client, code, status, error):
    client._session_token = "session"
    with aioresponses() as mock:
        mock.get(
            "https://192.0.2.254/api/v12/system/",
            status=status,
            payload={"success": False, "error_code": code, "msg": "secret-token"},
        )
        with pytest.raises(error) as exc:
            await client.get("system/")
        assert "secret-token" not in str(exc.value)


async def test_expired_session_is_renewed_once(client):
    client._session_token = "expired"
    with aioresponses() as mock:
        mock.get(
            "https://192.0.2.254/api/v12/system/", status=403, payload={"success": False, "error_code": "auth_required"}
        )
        mock.get("https://192.0.2.254/api/v12/login/", payload={"success": True, "result": {"challenge": "test"}})
        mock.post(
            "https://192.0.2.254/api/v12/login/session/", payload={"success": True, "result": {"session_token": "new"}}
        )
        mock.get("https://192.0.2.254/api/v12/system/", payload={"success": True, "result": {"uptime_val": 123}})
        assert await client.get("system/") == {"uptime_val": 123}


@pytest.mark.parametrize("body", ["not-json", "[]", '{"success": true}', '{"success": 1, "result": 42}'])
async def test_invalid_response(client, body):
    client._session_token = "session"
    with aioresponses() as mock:
        mock.get("https://192.0.2.254/api/v12/system/", body=body)
        with pytest.raises(FreeboxError):
            await client.get("system/")


def test_freebox_legacy_chain_extensions_remain_compatible():
    context = tls_context()
    assert not context.verify_flags & ssl.VERIFY_X509_STRICT
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
