from copy import deepcopy

from custom_components.freebox_ultra_ultimate.events import EventEngine
from tests.test_models import make_model


def test_disabled_new_device_tracking_retains_existing_only(responses, options):
    model, collectors = make_model(responses, options)
    model.inventory.initialized = True
    host = deepcopy(responses["lan/browser/pub/"][0])
    host["l2ident"]["id"] = "02:00:00:00:00:02"
    collectors.snapshots["lan/browser/pub/"].value.append(host)
    options["track_new_devices"] = False
    model.build(collectors, options)
    assert len(model.inventory.devices) == 1


def test_missing_client_from_complete_lan_list_goes_offline(responses, options):
    model, collectors = make_model(responses, options)
    options["families"].remove("wifi_clients")
    collectors.snapshots["lan/browser/pub/"].value = []
    collectors.changed = {"lan/browser/pub/"}
    model.build(collectors, options)
    assert model.inventory.devices["mac:02:00:00:00:00:01"].online is False


def test_disabled_wifi_details_do_not_create_station_gauges(responses, options):
    options["detailed_devices"] = False
    model, _ = make_model(responses, options)
    assert not any(key.endswith("wifi.rx_rate") for key in model.metrics)
    assert any(key.endswith(":tracker") for key in model.metrics)


def test_last_connected_timestamp_is_real_transition_only(responses, options):
    model, _ = make_model(responses, options)
    device = model.inventory.devices["mac:02:00:00:00:00:01"]
    assert device.last_connected is None
    engine = EventEngine(model.inventory, options, "salt")
    engine.payload("device_connected", device.key + ":online", False, True, 1700000300)
    assert device.last_connected == 1700000300


def test_malformed_nested_station_data_is_tolerated(responses, options):
    responses["wifi/ap/"][0]["config"] = None
    responses["wifi/ap/0/"]["config"] = None
    responses["wifi/ap/0/stations/"][0]["flags"] = None
    model, _ = make_model(responses, options)
    assert len(model.inventory.devices) == 1
