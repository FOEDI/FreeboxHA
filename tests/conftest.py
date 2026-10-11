import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freebox_ultra_ultimate.api import ApiVersion, EndpointUnavailable
from custom_components.freebox_ultra_ultimate.const import DEFAULT_OPTIONS, DOMAIN, FAMILIES


@pytest.fixture(autouse=True)
def custom_integration(enable_custom_integrations):
    yield


@pytest.fixture
def responses():
    return json.loads((Path(__file__).parent / "fixtures/freebox.json").read_text())


@pytest.fixture
def options():
    return {
        **deepcopy(DEFAULT_OPTIONS),
        "families": list(FAMILIES),
        "detailed_devices": True,
        "advanced_metrics": True,
        "group_by_name": False,
    }


@pytest.fixture
def entry():
    return MockConfigEntry(
        domain=DOMAIN,
        minor_version=2,
        unique_id="test-box",
        title="Freebox HA",
        data={"host": "192.0.2.254", "port": 443, "app_id": "test.app", "app_token": "secret"},
        options={
            "families": [
                "wan",
                "fibre",
                "system",
                "presence",
                "wifi_clients",
                "wifi_radios",
                "ethernet",
                "dhcp",
                "storage",
            ],
            "websocket": False,
            "advanced_metrics": True,
            "detailed_devices": True,
            "group_by_name": False,
        },
    )


@pytest.fixture
def api_mock(responses):
    class Api:
        def __init__(self):
            self.version = ApiVersion.parse(
                {"uid": "test-box", "api_version": "12.7", "api_domain": "example.fbxos.fr"}
            )
            self.permissions = {}
            self.discover = AsyncMock(return_value=self.version)
            self.login = AsyncMock()
            self.close = AsyncMock()
            self.get = AsyncMock(side_effect=self.get_response)

        async def get_response(self, path):
            if path not in responses:
                raise EndpointUnavailable("not_found", 404)
            return deepcopy(responses[path])

    return Api()


@pytest.fixture
def mock_api_factory(api_mock):
    with patch("custom_components.freebox_ultra_ultimate.create_client", return_value=api_mock):
        yield api_mock


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


@pytest.fixture(autouse=True)
def mock_zeroconf_setup():
    with patch("homeassistant.components.zeroconf.async_setup", new=AsyncMock(return_value=True)):
        yield


@pytest.fixture
async def client():
    import aiohttp

    from custom_components.freebox_ultra_ultimate.api import FreeboxClient, tls_context

    async with aiohttp.ClientSession() as session:
        api = FreeboxClient(session, tls_context(), host="192.0.2.254", app_id="test.app", app_token="secret")
        api.version = ApiVersion.parse({"uid": "test-box", "api_version": "12.7", "api_domain": "example.fbxos.fr"})
        yield api
