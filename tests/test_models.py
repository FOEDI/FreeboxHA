from copy import deepcopy

from custom_components.freebox_ultra_ultimate.capabilities import Capability
from custom_components.freebox_ultra_ultimate.collectors import Collectors, Snapshot
from custom_components.freebox_ultra_ultimate.inventory import Inventory, identity, normalize_mac
from custom_components.freebox_ultra_ultimate.metrics import describe, number
from custom_components.freebox_ultra_ultimate.models import Model


def make_model(responses, options, inventory=None):
    collectors = Collectors(None)
    for path, value in responses.items():
        if path.startswith("lan/"):
            family = "presence"
        elif path.startswith("wifi/"):
            family = (
                "wifi_clients"
                if path.endswith("stations/")
                else "wifi_environment"
                if path.endswith(("channel_usage/", "neighbors/"))
                else "wifi_radios"
            )
        elif path.startswith("connection/"):
            family = "fibre" if "ftth" in path else "wan"
        elif path.startswith("switch/"):
            family = "ethernet"
        else:
            family = path.split("/")[0]
        collectors.snapshots[path] = Snapshot(deepcopy(value), 1700000100, family)
        collectors.capabilities[path] = Capability(status="supported")
        collectors.changed.add(path)
    model = Model(inventory or Inventory())
    model.build(collectors, options)
    return model, collectors


def test_identity_is_mac_not_ip_or_name():
    assert (
        identity({"l2ident": {"type": "mac_address", "id": "02:AB:CD:00:01:02"}, "primary_name": "one"}, "pub")
        == "mac:02:ab:cd:00:01:02"
    )
    assert identity({"l2ident": [{"id": "02:AB:CD:00:01:02"}]}, "guest") == "mac:02:ab:cd:00:01:02"
    assert identity({"id": "xyz"}, "pub") == "host:pub:xyz"
    assert identity({"ip": "192.0.2.1", "hostname": "one"}, "pub") is None
    assert normalize_mac("BAD") is None


def test_fuses_lan_dhcp_and_wifi(responses, options):
    model, _ = make_model(responses, options)
    assert len(model.inventory.devices) == 1
    device = model.inventory.devices["mac:02:00:00:00:00:01"]
    assert device.online and device.reserved and device.private_mac
    assert device.connection == "wifi" and device.band == "6g"
    assert device.ipv4 == ("192.0.2.10",)
    assert device.ipv6 == ("2001:db8::10",)
    assert model.metrics[device.key + ":wifi.last_rx.bitrate"].value == 2400
    assert model.metrics[device.key + ":wifi.rx_rate"].value == 1
    assert model.metrics[device.key + ":wifi.signal"].unit == "dB"


def test_wan_fibre_switch_and_hardware_units(responses, options):
    model, _ = make_model(responses, options)
    assert model.metrics["wan:rate_down"].value == 1000
    assert model.metrics["wan:bandwidth_down"].value == 8000
    assert model.metrics["wan:bytes_down"].state_class == "total_increasing"
    assert model.metrics["fibre:sfp_pwr_rx"].value == -18.09
    assert model.metrics["fibre:sfp_pwr_tx"].value == 7.12
    assert model.metrics["port:1:speed"].value == 10000
    assert model.metrics["port:1:stats.rx_bytes_rate"].value == 10
    assert model.metrics["box:sensors:temp_t1"].device_class == "temperature"
    assert model.metrics["box:fans:fan0_speed"].unit == "rpm"
    assert model.metrics["partition:3:free_bytes"].value == 700000000


def test_optical_power_absent_not_zero(responses, options):
    responses["connection/ftth/"]["sfp_has_power_report"] = False
    model, _ = make_model(responses, options)
    assert "fibre:sfp_pwr_rx" not in model.metrics


def test_unknown_negative_phy_is_not_measurement(options):
    assert describe("phone", "last_rx.bitrate", -1, "wifi/ap/0/stations/", "wifi_clients", options) is None
    assert number(True) is None
    assert number("NaN") is None


def test_unknown_metrics_require_option_and_have_no_invented_unit(options):
    assert describe("box", "novel_counter", 42, "system/", "system", options) is None
    options["unknown_metrics"] = True
    metric = describe("box", "novel_counter", 42, "system/", "system", options)
    assert metric.unit is None and metric.state_class is None and metric.enabled is False


def test_secrets_never_become_entities(responses, options):
    options["unknown_metrics"] = True
    model, _ = make_model(responses, options)
    assert all("key" not in key for key in model.metrics)
    assert all(metric.value != "never-cache-this" for metric in model.metrics.values())


def test_identifiers_survive_name_and_ip_change(responses, options):
    model, _ = make_model(responses, options)
    key = next(iter(model.inventory.devices))
    responses["lan/browser/pub/"][0]["primary_name"] = "New name"
    responses["lan/browser/pub/"][0]["l3connectivities"] = [{"addr": "192.0.2.20"}]
    updated, _ = make_model(responses, options, model.inventory)
    assert set(updated.inventory.devices) == {key}
    assert updated.inventory.devices[key].ipv4 == ("192.0.2.20",)


def test_private_mac_is_not_merged_by_name(responses, options):
    duplicate = deepcopy(responses["lan/browser/pub/"][0])
    duplicate["l2ident"]["id"] = "02:00:00:00:00:02"
    responses["lan/browser/pub/"].append(duplicate)
    model, _ = make_model(responses, options)
    assert len(model.inventory.devices) == 2


def test_restore_retains_identity_not_online_state(responses, options):
    model, _ = make_model(responses, options)
    inventory = Inventory()
    inventory.restore(model.inventory.export())
    assert len(inventory.devices) == 1
    assert inventory.devices[next(iter(inventory.devices))].online is None
