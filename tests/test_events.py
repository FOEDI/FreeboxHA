from copy import deepcopy

import pytest

from custom_components.freebox_ultra_ultimate.events import EventEngine
from tests.test_models import make_model

KEY = "mac:02:00:00:00:00:01"


def observe(engine, model, healthy, changed, now, key, value, path="lan/browser/pub/"):
    model.observations = {key: (value, path)}
    return engine.update(model, healthy, changed, now)


def test_disconnect_requires_two_fresh_samples_and_delay(responses, options):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    key = KEY + ":online"
    assert not observe(engine, model, paths, paths, 0, key, True)
    assert not observe(engine, model, paths, paths, 20, key, False)
    assert not observe(engine, model, paths, paths, 40, key, False)
    events = observe(engine, model, paths, paths, 60, key, False)
    assert len(events) == 1 and events[0]["event_type"] == "freebox_ultra_device_disconnected"
    assert events[0]["device_id"] == KEY and events[0]["old_value"] is True
    assert not observe(engine, model, paths, paths, 80, key, False)


def test_brief_disconnect_is_cancelled(responses, options):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    key = KEY + ":online"
    observe(engine, model, paths, paths, 0, key, True)
    observe(engine, model, paths, paths, 10, key, False)
    assert not observe(engine, model, paths, paths, 20, key, True)
    assert not engine.pending


def test_api_outage_and_return_emit_no_fictional_disconnect(responses, options):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    key = KEY + ":online"
    observe(engine, model, paths, paths, 0, key, True)
    observe(engine, model, paths, paths, 20, key, False)
    assert not observe(engine, model, paths - {"lan/browser/pub/"}, set(), 100, key, False)
    assert not observe(engine, model, paths, paths, 200, key, False)


def test_pending_requires_new_endpoint_observation(responses, options):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    key = KEY + ":online"
    observe(engine, model, paths, paths, 0, key, True)
    observe(engine, model, paths, paths, 20, key, False)
    assert not observe(engine, model, paths, set(), 100, key, False)
    assert engine.pending[key].samples == 1


@pytest.mark.parametrize(
    ("key", "old", "new", "path", "kind"),
    [
        (KEY + ":online", False, True, "lan/browser/pub/", "device_connected"),
        (KEY + ":ip", (("192.0.2.10",), ()), (("192.0.2.20",), ()), "lan/browser/pub/", "device_ip_changed"),
        (KEY + ":connection", "wifi", "ethernet", "lan/browser/pub/", "device_connection_changed"),
        (KEY + ":band", "5g", "6g", "wifi/ap/0/stations/", "wifi_band_changed"),
        (KEY + ":ap", "0", "1", "wifi/ap/0/stations/", "wifi_client_roamed"),
        ("port:1:link", True, False, "switch/status/", "ethernet_link_down"),
        ("port:1:link", False, True, "switch/status/", "ethernet_link_up"),
        ("wan:connected", True, False, "connection/", "wan_disconnected"),
        ("wan:connected", False, True, "connection/", "wan_reconnected"),
    ],
)
def test_all_transition_events(responses, options, key, old, new, path, kind):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    observe(engine, model, paths, paths, 0, key, old, path)
    observe(engine, model, paths, paths, 20, key, new, path)
    events = observe(engine, model, paths, paths, 40, key, new, path)
    assert any(event["event_type"] == "freebox_ultra_" + kind for event in events)


def test_new_device_discovered_only_after_initial_baseline(responses, options):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    assert not engine.update(model, paths, paths, 0)
    host = deepcopy(responses["lan/browser/pub/"][0])
    host["l2ident"]["id"] = "02:00:00:00:00:02"
    device = model.inventory.upsert(host, "pub", "lan/browser/pub/", 10)
    model.observed_devices.add(device.key)
    events = engine.update(model, paths, paths, 20)
    assert [event["event_type"] for event in events] == ["freebox_ultra_device_discovered"]
    assert not engine.update(model, paths, paths, 40)


@pytest.mark.parametrize(
    ("metric_key", "bad", "recovered", "kind"),
    [
        (KEY + ":wifi.signal", -80, -60, "wifi_signal_low"),
        ("fibre:sfp_pwr_rx", -30, -20, "fibre_signal_warning"),
        ("box:temp_cpub", 90, 60, "system_temperature_high"),
    ],
)
def test_threshold_debounce_hysteresis(responses, options, metric_key, bad, recovered, kind):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    model.metrics[metric_key].value = bad
    assert not engine.update(model, paths, paths, 0)
    events = engine.update(model, paths, paths, 40)
    assert any(e["event_type"] == "freebox_ultra_" + kind for e in events)
    assert not engine.update(model, paths, paths, 80)
    model.metrics[metric_key].value = recovered
    assert not engine.update(model, paths, paths, 100)
    model.metrics[metric_key].value = bad
    engine.update(model, paths, paths, 120)
    assert any(e["event_type"] == "freebox_ultra_" + kind for e in engine.update(model, paths, paths, 160))


def test_reboot_rebaselines_transitions(responses, options):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    observe(engine, model, paths, paths, 0, "wan:connected", True, "connection/")
    engine.invalidate()
    assert not observe(engine, model, paths, paths, 40, "wan:connected", False, "connection/")


def test_privacy_and_zero_history(responses, options):
    options["event_identity"] = False
    options["history_size"] = 0
    model, _ = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    event = engine.payload("device_ip_changed", KEY + ":ip", "192.0.2.10", "192.0.2.20", 0)
    assert "mac" not in event and "name" not in event
    assert event["device_id"] != KEY and event["new_value"] == "redacted"
    assert model.inventory.devices[KEY].history == []


@pytest.mark.parametrize("reboot", [False, True])
def test_unconfirmed_alert_is_reset_after_outage_or_reboot(responses, options, reboot):
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    paths = set(collectors.snapshots)
    model.metrics["box:temp_cpub"].value = 95
    assert not engine.update(model, paths, paths, 0)
    if reboot:
        engine.invalidate()
    else:
        assert not engine.update(model, paths - {"system/"}, set(), 50)
    assert not engine.update(model, paths, paths, 100)
    events = engine.update(model, paths, paths, 140)
    assert any(event["event_type"] == "freebox_ultra_system_temperature_high" for event in events)
