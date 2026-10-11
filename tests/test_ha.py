from copy import deepcopy

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.freebox_ultra_ultimate.api import AuthenticationError, FreeboxError
from custom_components.freebox_ultra_ultimate.const import DOMAIN
from custom_components.freebox_ultra_ultimate.diagnostics import async_get_config_entry_diagnostics
from tests.conftest import setup_entry


async def test_setup_creates_real_ha_entities_and_unloads(hass, entry, mock_api_factory):
    coordinator = await setup_entry(hass, entry)
    assert entry.state == ConfigEntryState.LOADED
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    domains = {item.domain for item in entities}
    assert {"sensor", "binary_sensor", "device_tracker", "event"} <= domains
    uid = "test-box:wan:rate_down"
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, uid)
    assert hass.states.get(entity_id).state == "1000.0"
    assert hass.states.get(entity_id).attributes["unit_of_measurement"] == "Mbit/s"
    tracker = er.async_get(hass).async_get_entity_id("device_tracker", DOMAIN, "test-box:mac:02:00:00:00:00:01:tracker")
    assert hass.states.get(tracker).state == "home"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    mock_api_factory.close.assert_awaited()
    assert coordinator._ws_task is None


async def test_reload_preserves_entity_unique_ids(hass, entry, mock_api_factory):
    await setup_entry(hass, entry)
    before = {e.unique_id: e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = {e.unique_id: e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert before == after


async def test_new_device_creates_entities_dynamically(hass, entry, mock_api_factory, responses):
    coordinator = await setup_entry(hass, entry)
    host = deepcopy(responses["lan/browser/pub/"][0])
    host["l2ident"]["id"] = "02:00:00:00:00:02"
    responses["lan/browser/pub/"].append(host)
    coordinator.collectors.due.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "device_tracker", DOMAIN, "test-box:mac:02:00:00:00:00:02:tracker"
    )
    assert entity_id is not None and hass.states.get(entity_id).state == "home"
    assert any(event["event_type"] == "freebox_ultra_device_discovered" for event in coordinator.latest_events)


async def test_diagnostics_never_export_credentials_or_network_identity(hass, entry, mock_api_factory):
    await setup_entry(hass, entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diagnostics)
    for private in (
        "secret",
        "192.0.2.10",
        "02:00:00:00:00:01",
        "Example phone",
        "example.fbxos.fr",
        "never-cache-this",
    ):
        assert private not in text
    assert diagnostics["api_version"] == "12.7"
    assert diagnostics["tracked_devices"] == 1


async def test_setup_rejected_token_requires_reauthentication(hass, entry, mock_api_factory):
    mock_api_factory.login.side_effect = AuthenticationError("invalid_token", 403)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_network_error_retries(hass, entry, mock_api_factory):
    mock_api_factory.discover.side_effect = FreeboxError("transport_error")
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state == ConfigEntryState.SETUP_RETRY


async def test_fibre_error_keeps_wan_sensor_available(hass, entry, mock_api_factory):
    coordinator = await setup_entry(hass, entry)
    original = mock_api_factory.get.side_effect

    async def get(path):
        if path == "connection/ftth/":
            raise FreeboxError("transport_error")
        return await original(path)

    mock_api_factory.get.side_effect = get
    coordinator.collectors.due.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    wan = registry.async_get_entity_id("sensor", DOMAIN, "test-box:wan:rate_down")
    fibre = registry.async_get_entity_id("sensor", DOMAIN, "test-box:fibre:sfp_pwr_rx")
    assert hass.states.get(wan).state != "unavailable"
    assert hass.states.get(fibre).state == "unavailable"


async def test_all_families_disabled_keeps_configuration_loaded(hass, entry, mock_api_factory):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "families": []})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert entry.state == ConfigEntryState.LOADED
    assert coordinator.model.metrics["box:diagnostic:tracked_devices"].value == 0
    mock_api_factory.get.assert_not_awaited()


async def test_inventory_checkpoint_is_not_postponed_on_each_refresh(hass, entry, mock_api_factory):
    from unittest.mock import AsyncMock

    coordinator = await setup_entry(hass, entry)
    coordinator.store.async_save = AsyncMock()
    coordinator._last_inventory_save = 0
    await coordinator.async_refresh()
    coordinator.store.async_save.assert_awaited_once()
    await coordinator.async_refresh()
    coordinator.store.async_save.assert_awaited_once()
    coordinator._last_inventory_save = 0
    await coordinator.async_refresh()
    assert coordinator.store.async_save.await_count == 2
