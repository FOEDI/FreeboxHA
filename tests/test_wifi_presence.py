"""Wi-Fi presence ignores delayed LAN status without treating silence as absence."""

from copy import deepcopy

import pytest

from custom_components.freebox_ultra_ultimate.const import DEFAULT_OPTIONS
from custom_components.freebox_ultra_ultimate.events import EventEngine
from custom_components.freebox_ultra_ultimate.inventory import Inventory
from tests.test_models import make_model

KEY = "mac:02:00:00:00:00:01"
PATH = "wifi/ap/0/stations/"


def leave_wifi(model, collectors, options):
    collectors.snapshots[PATH].value = []
    collectors.changed = {PATH}
    model.build(collectors, options)


def test_wifi_absence_overrides_delayed_active_lan(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    leave_wifi(model, collectors, options)
    assert collectors.snapshots["lan/browser/pub/"].value[0]["active"] is True
    assert model.metrics[KEY + ":tracker"].value is False
    assert model.metrics[KEY + ":connected"].value is False
    assert model.metrics[KEY + ":tracker"].attributes["connection_evidence"] == "wifi_absence"
    assert model.observations[KEY + ":online"] == (False, PATH)


def test_cached_wifi_absence_is_not_overridden_between_polls(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    leave_wifi(model, collectors, options)
    for changed in (set(), {"lan/browser/pub/"}):
        collectors.changed = changed
        model.build(collectors, options)
        assert model.metrics[KEY + ":tracker"].value is False
        assert KEY + ":online" not in model.observations


def test_station_association_overrides_inactive_lan(responses):
    responses["lan/browser/pub/"][0].update(active=False, reachable=False)
    model, _ = make_model(responses, deepcopy(DEFAULT_OPTIONS))
    assert model.metrics[KEY + ":tracker"].value is True
    assert model.metrics[KEY + ":tracker"].attributes["connection_evidence"] == "wifi_association"


def test_radio_failure_does_not_fall_back_to_stale_lan(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    collectors.capabilities[PATH].status = "error"
    collectors.changed = {"lan/browser/pub/"}
    model.build(collectors, options)
    assert model.metrics[KEY + ":tracker"].value is None
    assert model.observations[KEY + ":online"] == (None, PATH)
    assert model.metrics[KEY + ":tracker"].attributes["connection_evidence"] == "api_unavailable"


@pytest.mark.parametrize("station", [{"signal": -40}, {"mac": "02:00:00:00:00:01", "signal": -40}, None])
def test_signal_or_malformed_station_is_not_connection_proof(responses, station):
    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    collectors.snapshots[PATH].value = [station]
    collectors.changed = {PATH}
    model.build(collectors, options)
    assert model.metrics[KEY + ":tracker"].value is None


def test_sleeping_phone_is_not_disconnected_for_zero_traffic(responses):
    responses[PATH][0].update(inactive=7200, rx_rate=0, tx_rate=0)
    model, _ = make_model(responses, deepcopy(DEFAULT_OPTIONS))
    tracker = model.metrics[KEY + ":tracker"]
    assert tracker.value is True
    assert tracker.attributes["wifi_traffic_active"] is False
    assert tracker.attributes["wifi_inactive_seconds"] == 7200
    assert tracker.attributes["wifi_signal"] == -50
    assert tracker.attributes["wifi_signal_unit"] == "dB"


def test_known_wifi_classification_survives_restart(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    model, _ = make_model(responses, options)
    inventory = Inventory(group_by_name=True)
    inventory.restore(model.inventory.export())
    responses[PATH] = []
    restored, _ = make_model(responses, options, inventory)
    assert restored.metrics[KEY + ":tracker"].value is False


def test_wifi_debounce_uses_short_delay_and_only_complete_fresh_coverage(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    responses["wifi/ap/"].append({"id": 1})
    responses["wifi/ap/1/stations/"] = []
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    healthy = set(collectors.snapshots)
    engine.update(model, healthy, collectors.changed, 0)
    leave_wifi(model, collectors, options)
    assert KEY + ":online" not in model.observations
    assert not engine.update(model, healthy, collectors.changed, 10)
    collectors.changed = {PATH, "wifi/ap/1/stations/"}
    model.build(collectors, options)
    assert not engine.update(model, healthy, collectors.changed, 20)
    collectors.changed = set()
    model.build(collectors, options)
    assert not engine.update(model, healthy, collectors.changed, 30)
    collectors.changed = {PATH, "wifi/ap/1/stations/"}
    model.build(collectors, options)
    events = engine.update(model, healthy, collectors.changed, 30)
    assert engine.baseline[KEY + ":online"] is False
    assert [e["event_type"] for e in events] == ["freebox_ultra_device_disconnected"]


def test_short_wifi_roaming_does_not_fire_disconnect(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    healthy = set(collectors.snapshots)
    engine.update(model, healthy, collectors.changed, 0)
    station = deepcopy(collectors.snapshots[PATH].value)
    leave_wifi(model, collectors, options)
    engine.update(model, healthy, collectors.changed, 10)
    collectors.snapshots[PATH].value = station
    model.build(collectors, options)
    assert not engine.update(model, healthy, collectors.changed, 20)
    assert engine.baseline[KEY + ":online"] is True


def test_other_group_alias_stale_lan_does_not_keep_phone_online(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    host = deepcopy(responses["lan/browser/pub/"][0])
    host["l2ident"]["id"] = "02:00:00:00:00:02"
    responses["lan/browser/pub/"].append(host)
    model, collectors = make_model(responses, options)
    leave_wifi(model, collectors, options)
    assert len(model.inventory.devices) == 1
    assert model.metrics[KEY + ":tracker"].value is False


def test_wifi_disabled_keeps_lan_fallback(responses):
    options = deepcopy(DEFAULT_OPTIONS)
    model, collectors = make_model(responses, options)
    leave_wifi(model, collectors, options)
    options["families"].remove("wifi_clients")
    model.build(collectors, options)
    assert model.metrics[KEY + ":tracker"].value is True
    assert model.metrics[KEY + ":tracker"].attributes["connection_evidence"] == "lan_status"


async def test_real_ha_tracker_uses_radio_absence_and_exposes_debounce(hass, entry, mock_api_factory, responses):
    from unittest.mock import patch

    from homeassistant.helpers import entity_registry as er

    from custom_components.freebox_ultra_ultimate.const import DOMAIN
    from tests.conftest import setup_entry

    coordinator = await setup_entry(hass, entry)
    tracker = er.async_get(hass).async_get_entity_id("device_tracker", DOMAIN, "test-box:" + KEY + ":tracker")
    assert hass.states.get(tracker).state == "home"
    responses[PATH] = []
    with patch("custom_components.freebox_ultra_ultimate.coordinator.time.time", return_value=1700000200):
        coordinator._forced.add("wifi_clients")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    state = hass.states.get(tracker)
    assert state.state == "home"
    assert state.attributes["connected_observed"] is False
    assert state.attributes["presence_pending"] is True
    with patch("custom_components.freebox_ultra_ultimate.coordinator.time.time", return_value=1700000210):
        coordinator._forced.add("wifi_clients")
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    state = hass.states.get(tracker)
    assert state.state == "not_home"
    assert state.attributes["presence_pending"] is False
    assert state.attributes["connection_evidence"] == "wifi_absence"
    assert any(e["event_type"] == "freebox_ultra_device_disconnected" for e in coordinator.latest_events)


async def test_real_ha_tracker_unavailable_during_wifi_failure(hass, entry, mock_api_factory):
    from homeassistant.helpers import entity_registry as er

    from custom_components.freebox_ultra_ultimate.api import FreeboxError
    from custom_components.freebox_ultra_ultimate.const import DOMAIN
    from tests.conftest import setup_entry

    coordinator = await setup_entry(hass, entry)
    original = mock_api_factory.get.side_effect

    async def get(path):
        if path == PATH:
            raise FreeboxError("transport_error")
        return await original(path)

    mock_api_factory.get.side_effect = get
    coordinator.collectors.due.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    tracker = er.async_get(hass).async_get_entity_id("device_tracker", DOMAIN, "test-box:" + KEY + ":tracker")
    assert hass.states.get(tracker).state == "unavailable"
    assert not coordinator.latest_events
