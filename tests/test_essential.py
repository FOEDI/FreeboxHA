"""Essential defaults and explicit same-name network identity consolidation."""

from copy import deepcopy

from custom_components.freebox_ultra_ultimate.const import DEFAULT_OPTIONS
from custom_components.freebox_ultra_ultimate.inventory import Inventory
from tests.test_models import make_model


def test_essential_defaults_keep_only_monitoring_families():
    assert set(DEFAULT_OPTIONS["families"]) == {
        "wan",
        "fibre",
        "presence",
        "wifi_clients",
        "wifi_radios",
        "ethernet",
        "system",
    }
    assert DEFAULT_OPTIONS["detailed_devices"] is False
    assert DEFAULT_OPTIONS["advanced_metrics"] is False
    assert DEFAULT_OPTIONS["group_by_name"] is True


def test_same_named_macs_have_one_tracker_and_union_presence(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    host = responses["lan/browser/pub/"][0]
    host.update(active=False, reachable=False)
    second = deepcopy(host)
    second["l2ident"]["id"] = "02:00:00:00:00:02"
    second.update(active=True, reachable=True)
    responses["lan/browser/pub/"].append(second)
    responses["wifi/ap/0/stations/"] = []
    model, _ = make_model(responses, options)
    assert len(model.inventory.devices) == 1
    assert next(iter(model.inventory.devices.values())).online is True
    enabled = [m for m in model.metrics.values() if m.enabled and m.device.startswith("mac:")]
    assert len(enabled) == 1 and enabled[0].platform == "device_tracker"


def test_group_aliases_survive_restart_and_name_change(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    second = deepcopy(responses["lan/browser/pub/"][0])
    second["l2ident"]["id"] = "02:00:00:00:00:02"
    responses["lan/browser/pub/"].append(second)
    model, _ = make_model(responses, options)
    key = next(iter(model.inventory.devices))
    saved = model.inventory.export()
    restored = Inventory(group_by_name=True)
    restored.restore(saved)
    second["primary_name"] = "Renamed phone"
    responses["lan/browser/pub/"] = [second]
    responses["wifi/ap/0/stations/"] = []
    updated, _ = make_model(responses, options, restored)
    assert set(updated.inventory.devices) == {key}
    assert updated.inventory.devices[key].name == "Renamed phone"


def test_legacy_inventory_merges_three_named_entries():
    inventory = Inventory(group_by_name=True)
    inventory.restore(
        {
            "devices": [
                {"key": f"mac:02:00:00:00:00:0{i}", "mac": f"02:00:00:00:00:0{i}", "name": "S25 Ultra", "first_seen": i}
                for i in (1, 2, 3)
            ]
        }
    )
    assert len(inventory.devices) == 1
    assert inventory.resolve("mac:02:00:00:00:00:03") == "mac:02:00:00:00:00:01"


def test_different_names_and_unnamed_hosts_stay_separate():
    inventory = Inventory(group_by_name=True)
    for suffix, name in [(1, "S25 Ultra"), (2, "Other phone"), (3, None), (4, None)]:
        inventory.upsert({"mac": f"02:00:00:00:00:0{suffix}", "hostname": name}, "pub", "lan/browser/pub/", 1)
    assert len(inventory.devices) == 4


def test_grouping_can_be_disabled(responses, options):
    options["group_by_name"] = False
    second = deepcopy(responses["lan/browser/pub/"][0])
    second["l2ident"]["id"] = "02:00:00:00:00:02"
    responses["lan/browser/pub/"].append(second)
    model, _ = make_model(responses, options)
    assert len(model.inventory.devices) == 2


def test_wifi_details_off_keeps_signal_alert_source(responses):
    model, _ = make_model(responses, deepcopy(DEFAULT_OPTIONS))
    metric = model.metrics["mac:02:00:00:00:00:01:wifi.signal"]
    assert metric.value == -50 and metric.enabled is False


def test_tracker_wifi_context_without_technical_sensors(responses):
    model, _ = make_model(responses, deepcopy(DEFAULT_OPTIONS))
    tracker = model.metrics["mac:02:00:00:00:00:01:tracker"]
    assert tracker.attributes["connection_type"] == "wifi"
    assert tracker.attributes["ssid"] == "Example network"
    assert tracker.attributes["wifi_band"] == "6g"
    assert tracker.attributes["access_point"] == "0"
    assert "mac:02:00:00:00:00:01:wifi.rx_rate" not in model.metrics


def test_tracker_context_clears_when_not_associated(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    collectors.snapshots["wifi/ap/0/stations/"].value = []
    collectors.changed = {"wifi/ap/0/stations/"}
    model.build(collectors, options)
    tracker = model.metrics["mac:02:00:00:00:00:01:tracker"]
    assert tracker.attributes["ssid"] is None
    assert tracker.attributes["wifi_bands"] == []


def test_grouped_wifi_presence_continues_across_mac_and_band_change(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    original = next(iter(model.inventory.devices))
    station = collectors.snapshots["wifi/ap/0/stations/"].value[0]
    station["mac"] = "02:00:00:00:00:02"
    model.build(collectors, options)
    assert set(model.inventory.devices) == {original}
    assert model.metrics[original + ":tracker"].value is True
    assert model.inventory.resolve("mac:02:00:00:00:00:02") == original


async def test_existing_ha_devices_and_entities_are_consolidated(hass, entry, mock_api_factory, responses):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.freebox_ultra_ultimate.const import DOMAIN

    legacy = MockConfigEntry(domain=DOMAIN, data=entry.data, unique_id="test-box", version=1, minor_version=1)
    legacy.add_to_hass(hass)
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    for i in (1, 2, 3):
        mac = f"02:00:00:00:00:0{i}"
        host = deepcopy(responses["lan/browser/pub/"][0])
        host["l2ident"]["id"] = mac
        if i > 1:
            responses["lan/browser/pub/"].append(host)
        device = devices.async_get_or_create(
            config_entry_id=legacy.entry_id, identifiers={(DOMAIN, f"test-box:mac:{mac}")}, name="Example phone"
        )
        registry.async_get_or_create(
            "device_tracker", DOMAIN, f"test-box:mac:{mac}:tracker", config_entry=legacy, device_id=device.id
        )
    old_sensor = registry.async_get_or_create(
        "sensor", DOMAIN, "test-box:mac:02:00:00:00:00:01:first_seen", config_entry=legacy
    )
    assert await hass.config_entries.async_setup(legacy.entry_id)
    await hass.async_block_till_done()
    trackers = [e for e in er.async_entries_for_config_entry(registry, legacy.entry_id) if e.domain == "device_tracker"]
    assert len(trackers) == 1 and hass.states.get(trackers[0].entity_id).state == "home"
    assert registry.async_get(old_sensor.entity_id).disabled_by == er.RegistryEntryDisabler.INTEGRATION
    phones = [d for d in dr.async_entries_for_config_entry(devices, legacy.entry_id) if d.name == "Example phone"]
    assert len(phones) == 1
    assert legacy.minor_version == 2 and legacy.options["advanced_metrics"] is False
    assert legacy.options["apply_entity_defaults"] is False
    for e in er.async_entries_for_config_entry(registry, legacy.entry_id):
        if e.unique_id.startswith("test-box:mac:") and e.domain != "device_tracker":
            assert e.disabled_by == er.RegistryEntryDisabler.INTEGRATION


async def test_essential_options_reset_existing_profile(hass, entry):
    from homeassistant.data_entry_flow import FlowResultType

    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "essential"})
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["group_by_name"] is True
    assert entry.options["detailed_devices"] is False
    assert entry.options["families"] == DEFAULT_OPTIONS["families"]
    assert entry.options["apply_entity_defaults"] is True


async def test_manual_sensor_enable_survives_reload(hass, entry, mock_api_factory):
    from homeassistant.helpers import entity_registry as er

    from custom_components.freebox_ultra_ultimate.const import DOMAIN

    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={**deepcopy(DEFAULT_OPTIONS), "websocket": False})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    sensor = registry.async_get_entity_id("sensor", DOMAIN, "test-box:mac:02:00:00:00:00:01:connection_type")
    assert registry.async_get(sensor).disabled_by == er.RegistryEntryDisabler.INTEGRATION
    registry.async_update_entity(sensor, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(sensor).disabled_by is None
    assert hass.states.get(sensor).state == "wifi"


def test_tracker_wifi_identity_can_be_hidden(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    options["expose_identity"] = False
    model, _ = make_model(responses, options)
    tracker = model.metrics["mac:02:00:00:00:00:01:tracker"]
    assert "ssid" not in tracker.attributes and "ssids" not in tracker.attributes


def test_disabling_grouping_restores_member_identities(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    second = deepcopy(responses["lan/browser/pub/"][0])
    second["l2ident"]["id"] = "02:00:00:00:00:02"
    responses["lan/browser/pub/"].append(second)
    model, _ = make_model(responses, options)
    assert len(model.inventory.devices) == 1
    options["group_by_name"] = False
    updated, _ = make_model(responses, options, model.inventory)
    assert set(updated.inventory.devices) == {"mac:02:00:00:00:00:01", "mac:02:00:00:00:00:02"}


def test_mac_handoff_emits_no_discovery_or_disconnect(responses):
    from custom_components.freebox_ultra_ultimate.events import EventEngine

    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    healthy = set(collectors.snapshots)
    engine.update(model, healthy, collectors.changed, 0)
    collectors.snapshots["wifi/ap/0/stations/"].value[0]["mac"] = "02:00:00:00:00:02"
    model.build(collectors, options)
    events = engine.update(model, healthy, collectors.changed, 100)
    assert not any(
        event["event_type"]
        in {"freebox_ultra_device_discovered", "freebox_ultra_device_connected", "freebox_ultra_device_disconnected"}
        for event in events
    )


async def test_group_cleanup_preserves_other_integrations(hass, entry, mock_api_factory):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.freebox_ultra_ultimate.const import DOMAIN
    from custom_components.freebox_ultra_ultimate.entity import consolidate_devices
    from tests.conftest import setup_entry

    coordinator = await setup_entry(hass, entry)
    other = MockConfigEntry(domain="test_other")
    other.add_to_hass(hass)
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    alias = "mac:02:00:00:00:00:02"
    old = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, "test-box:" + alias)})
    other_device = devices.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={(DOMAIN, "test-box:" + alias)}
    )
    shared = registry.async_get_or_create(
        "sensor", "test_other", "shared", config_entry=other, device_id=other_device.id
    )
    coordinator.inventory.group_by_name = True
    coordinator.inventory.aliases[alias] = "mac:02:00:00:00:00:01"
    consolidate_devices(hass, entry, coordinator)
    assert registry.async_get(shared.entity_id) is not None
    assert devices.async_get(old.id) is None
    assert devices.async_get(other_device.id) is not None


def test_opted_in_category_exposes_operational_metrics(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    options["families"].append("storage")
    model, _ = make_model(responses, options)
    assert model.metrics["partition:3:free_bytes"].enabled is True
