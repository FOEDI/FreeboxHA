"""Firmware empty collections must produce absence, never lose device metadata."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.freebox_ultra_ultimate.api import FreeboxError
from custom_components.freebox_ultra_ultimate.collectors import Collectors
from custom_components.freebox_ultra_ultimate.const import DOMAIN
from tests.conftest import setup_entry
from tests.http_mock import HttpMock

KEY = "mac:02:00:00:00:00:01"
PATH = "wifi/ap/0/stations/"


@pytest.mark.parametrize("value", [{}, None])
@pytest.mark.parametrize("path", [PATH, "lan/browser/guest/"])
async def test_successful_empty_network_collection_is_healthy(api_mock, value, path):
    api_mock.get = AsyncMock(return_value=value)
    collectors = Collectors(api_mock)
    assert await collectors.fetch(path, "list", "wifi_clients") == []
    assert collectors.healthy(path)
    assert collectors.capabilities[path].response_type == type(value).__name__


@pytest.mark.parametrize("path", ["wifi/ap/", "lan/browser/interfaces/", "downloads/"])
@pytest.mark.parametrize("value", [{}, None, {"unexpected": []}])
async def test_non_network_lists_remain_strict(api_mock, path, value):
    api_mock.get = AsyncMock(return_value=value)
    collectors = Collectors(api_mock)
    assert await collectors.fetch(path, "list", "wifi_radios") is None
    assert not collectors.healthy(path)
    assert collectors.capabilities[path].error == "invalid_shape"


async def test_non_network_get_missing_result_is_rejected(client):
    client._session_token = "test-session"
    with HttpMock() as http:
        http.get("https://192.0.2.254/api/v12/system/", payload={"success": True})
        with pytest.raises(FreeboxError, match="invalid_envelope"):
            await client.get("system/")


@pytest.mark.parametrize("empty", [{}, None])
async def test_ha_empty_station_format_produces_absence_with_identity_retained(
    hass, entry, mock_api_factory, responses, empty
):
    from unittest.mock import patch

    coordinator = await setup_entry(hass, entry)
    saved_first_seen = coordinator.inventory.devices[KEY].first_seen
    # Previously empty secondary radios blocked complete coverage.
    responses["wifi/ap/"].append({"id": 1})
    responses["wifi/ap/1/stations/"] = deepcopy(empty)
    responses[PATH] = deepcopy(empty)
    for now in (1700000200, 1700000210):
        coordinator.collectors.due.clear()
        with patch("custom_components.freebox_ultra_ultimate.coordinator.time.time", return_value=now):
            await coordinator.async_refresh()
            await hass.async_block_till_done()
    registry = er.async_get(hass)
    tracker = registry.async_get_entity_id("device_tracker", DOMAIN, "test-box:" + KEY + ":tracker")
    connected = registry.async_get_entity_id("binary_sensor", DOMAIN, "test-box:" + KEY + ":connected")
    assert hass.states.get(tracker).state == "not_home"
    assert hass.states.get(connected).state == "off"
    for suffix in ("hostname", "mac_address", "ipv4", "first_seen", "last_seen"):
        entity = registry.async_get_entity_id("sensor", DOMAIN, "test-box:" + KEY + ":" + suffix)
        state = hass.states.get(entity)
        assert state.state not in {"unavailable", "unknown"}
        assert state.attributes["data_source"] == "inventory"
    assert coordinator.inventory.devices[KEY].first_seen == saved_first_seen
    assert any(e["event_type"] == "freebox_ultra_device_disconnected" for e in coordinator.latest_events)


async def test_identity_available_on_api_failure_but_presence_is_unavailable(hass, entry, mock_api_factory):
    coordinator = await setup_entry(hass, entry)
    mock_api_factory.get.side_effect = FreeboxError("transport_error")
    coordinator.collectors.due.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    tracker = registry.async_get_entity_id("device_tracker", DOMAIN, "test-box:" + KEY + ":tracker")
    name = registry.async_get_entity_id("sensor", DOMAIN, "test-box:" + KEY + ":hostname")
    assert hass.states.get(tracker).state == "unavailable"
    assert hass.states.get(name).state == "Example phone"
    assert not coordinator.latest_events


@pytest.mark.parametrize("path", [PATH, "lan/browser/guest/"])
async def test_api16_network_success_without_result_is_empty(client, path):
    client._session_token = "test-session"
    with HttpMock() as http:
        http.get("https://192.0.2.254/api/v12/" + path, payload={"success": True})
        assert await client.get(path) == []
