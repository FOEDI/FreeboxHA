"""WebSocket behavior: verified subscriptions and authoritative refresh hints."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.freebox_ultra_ultimate.coordinator import WS_EVENTS, FreeboxCoordinator


class WebSocket:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.send_json = AsyncMock()
        self.closed = False
        self.messages = iter(
            [
                SimpleNamespace(
                    type=aiohttp.WSMsgType.TEXT,
                    data='{"action":"notification","success":true,"event":"lan_host_l3addr_reachable","result":{"active":false}}',
                )
            ]
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def receive(self):
        return SimpleNamespace(
            type=aiohttp.WSMsgType.TEXT,
            data='{"action":"register","success":' + ("true" if self.accepted else "false") + "}",
        )

    def __aiter__(self):
        return self

    async def __anext__(self):
        if item := next(self.messages, None):
            return item
        raise asyncio.CancelledError


async def test_websocket_notification_requests_poll_not_presence_change(hass, entry, api_mock):
    websocket = WebSocket()
    api_mock.open_websocket = AsyncMock(return_value=websocket)
    coordinator = FreeboxCoordinator(hass, entry, api_mock)
    coordinator.async_request_refresh = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await coordinator._websocket_loop()
    assert "presence" in coordinator._forced
    assert "wifi_clients" in coordinator._forced
    coordinator.async_request_refresh.assert_awaited_once()
    websocket.send_json.assert_awaited_once_with({"action": "register", "request_id": 1, "events": list(WS_EVENTS)})
    assert coordinator.websocket_status == "subscribed"
    assert not coordinator.inventory.devices
    assert websocket.closed


async def test_rejected_subscription_reports_polling_fallback(hass, entry, api_mock):
    websocket = WebSocket(False)
    api_mock.open_websocket = AsyncMock(return_value=websocket)
    coordinator = FreeboxCoordinator(hass, entry, api_mock)
    with pytest.raises(asyncio.CancelledError):
        from unittest.mock import patch

        with patch(
            "custom_components.freebox_ultra_ultimate.coordinator.asyncio.sleep", side_effect=asyncio.CancelledError
        ):
            await coordinator._websocket_loop()
    assert coordinator.websocket_status == "subscription_refused"
    assert websocket.closed
