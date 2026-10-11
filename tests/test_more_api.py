import asyncio
import ssl
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.freebox_ultra_ultimate.api import MAX_RESPONSE_BYTES, FreeboxError
from tests.http_mock import HttpMock


async def test_concurrent_first_login_is_single(client):
    async def call(method, path, **kwargs):
        await asyncio.sleep(0)
        if path == "login/":
            return {"challenge": "challenge"}
        if path == "login/session/":
            return {"session_token": "session"}
        return {"value": 1}

    with patch.object(client, "_call", new=AsyncMock(side_effect=call)) as request:
        assert await asyncio.gather(*(client.get("system/") for _ in range(8))) == [{"value": 1}] * 8
        assert sum(call.args[1] == "login/session/" for call in request.call_args_list) == 1


async def test_no_auth_token_on_metadata_and_verified_tls_on_login(client):
    from tests.test_api import META

    with HttpMock() as mock:
        mock.get("http://192.0.2.254/api_version", payload=META)
        mock.get("https://192.0.2.254/api_version", payload=META)
        await client.discover()
        assert mock.calls[0][2]["headers"] == {}
        assert mock.calls[1][2]["ssl"].verify_mode == ssl.CERT_REQUIRED
        assert mock.calls[1][2]["server_hostname"] == META["api_domain"]
        assert all(call[2]["allow_redirects"] is False for call in mock.calls)


async def test_huge_response_rejected(client):
    client._session_token = "session"
    with HttpMock() as mock:
        mock.get("https://192.0.2.254/api/v12/system/", body="x" * (MAX_RESPONSE_BYTES + 10))
        with pytest.raises(FreeboxError, match="response_too_large"):
            await client.get("system/")


async def test_auth_post_whitelist_and_logout(client):
    client._session_token = "session"
    with HttpMock() as mock:
        mock.post("https://192.0.2.254/api/v12/login/logout/", payload={"success": True})
        await client.close()
        assert client._session_token is None
        assert mock.calls[0][0:2] == ("POST", "https://192.0.2.254/api/v12/login/logout/")
