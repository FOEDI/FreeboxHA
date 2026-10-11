from copy import deepcopy

import pytest

from custom_components.freebox_ultra_ultimate.api import FreeboxError
from custom_components.freebox_ultra_ultimate.collectors import Collectors
from custom_components.freebox_ultra_ultimate.events import EventEngine
from tests.test_models import make_model


@pytest.mark.parametrize(
    "family,root,child",
    [
        ("presence", "lan/browser/interfaces/", "lan/browser/pub/"),
        ("wifi_clients", "wifi/ap/", "wifi/ap/0/stations/"),
        ("ethernet", "switch/status/", "switch/port/1/stats"),
    ],
)
async def test_failed_discovery_invalidates_children(api_mock, options, family, root, child):
    options["families"] = [family]
    collectors = Collectors(api_mock)
    await collectors.update(options)
    assert collectors.healthy(child)
    original = api_mock.get.side_effect

    async def get(path):
        if path == root:
            raise FreeboxError("transport_error")
        return await original(path)

    api_mock.get.side_effect = get
    await collectors.update(options, {family})
    assert not collectors.healthy(child)
    assert child in collectors.snapshots


def test_partial_lan_cannot_prove_absence(responses, options):
    options["families"] = ["presence"]
    host = deepcopy(responses["lan/browser/pub/"][0])
    responses["lan/browser/a/"] = [deepcopy(host)]
    responses["lan/browser/a/"][0].update(active=False, reachable=False)
    responses["lan/browser/b/"] = [host]
    del responses["lan/browser/pub/"]
    model, collectors = make_model(responses, options)
    engine = EventEngine(model.inventory, options, "salt")
    healthy = set(collectors.snapshots)
    engine.update(model, healthy, healthy, 0)
    collectors.capabilities["lan/browser/b/"].status = "error"
    collectors.changed = {"lan/browser/a/"}
    for now in (10, 100):
        model.build(collectors, options)
        events = engine.update(model, healthy - {"lan/browser/b/"}, collectors.changed, now)
        assert not events
        assert model.inventory.devices["mac:02:00:00:00:00:01"].online is None
    assert "mac:02:00:00:00:00:01:online" not in engine.baseline


def test_wifi_only_client_disappearance_is_confirmed(responses, options):
    options["families"] = ["wifi_clients"]
    model, collectors = make_model(responses, options)
    key = "mac:02:00:00:00:00:01"
    engine = EventEngine(model.inventory, options, "salt")
    healthy = set(collectors.snapshots)
    engine.update(model, healthy, healthy, 0)
    collectors.snapshots["wifi/ap/0/stations/"].value = []
    collectors.changed = {"wifi/ap/0/stations/"}
    model.build(collectors, options)
    assert model.inventory.devices[key].online is False
    assert not engine.update(model, healthy, collectors.changed, 10)
    model.build(collectors, options)
    assert [e["event_type"] for e in engine.update(model, healthy, collectors.changed, 100)] == [
        "freebox_ultra_device_disconnected"
    ]


def test_partial_wifi_cannot_prove_absence(responses, options):
    options["families"] = ["wifi_clients"]
    responses["wifi/ap/1/stations/"] = []
    model, collectors = make_model(responses, options)
    collectors.snapshots["wifi/ap/0/stations/"].value = []
    collectors.capabilities["wifi/ap/1/stations/"].status = "error"
    collectors.changed = {"wifi/ap/0/stations/"}
    model.build(collectors, options)
    assert model.inventory.devices["mac:02:00:00:00:00:01"].online is None


def test_wifi_roaming_does_not_disconnect(responses, options):
    options["families"] = ["wifi_clients"]
    responses["wifi/ap/1/stations/"] = []
    model, collectors = make_model(responses, options)
    station = collectors.snapshots["wifi/ap/0/stations/"].value.pop()
    collectors.snapshots["wifi/ap/1/stations/"].value.append(station)
    collectors.changed = {"wifi/ap/0/stations/", "wifi/ap/1/stations/"}
    model.build(collectors, options)
    device = model.inventory.devices["mac:02:00:00:00:00:01"]
    assert device.online is True and device.ap_id == "1"


def test_initial_wifi_inventory_when_new_device_tracking_disabled(responses, options):
    options["families"] = ["wifi_clients"]
    options["track_new_devices"] = False
    model, _ = make_model(responses, options)
    assert "mac:02:00:00:00:00:01" in model.inventory.devices


def test_unreachable_new_ap_cannot_prove_wifi_absence(responses, options):
    from custom_components.freebox_ultra_ultimate.capabilities import Capability

    options["families"] = ["wifi_clients"]
    responses["wifi/ap/"].append({"id": 1})
    model, collectors = make_model(responses, options)
    collectors.capabilities["wifi/ap/1/stations/"] = Capability(status="error")
    collectors.snapshots["wifi/ap/0/stations/"].value = []
    collectors.changed = {"wifi/ap/0/stations/"}
    model.build(collectors, options)
    assert model.inventory.devices["mac:02:00:00:00:00:01"].online is None


@pytest.mark.parametrize(
    "family,root,child",
    [
        ("presence", "lan/browser/interfaces/", "lan/browser/pub/"),
        ("wifi_clients", "wifi/ap/", "wifi/ap/0/stations/"),
        ("ethernet", "switch/status/", "switch/port/1/stats"),
    ],
)
async def test_removed_discovery_child_becomes_unavailable(api_mock, options, family, root, child):
    options["families"] = [family]
    collectors = Collectors(api_mock)
    await collectors.update(options)
    assert collectors.healthy(child)
    original = api_mock.get.side_effect

    async def get(path):
        if path == root:
            return []
        return await original(path)

    api_mock.get.side_effect = get
    await collectors.update(options, {family})
    assert not collectors.healthy(child)
