from unittest.mock import AsyncMock

from custom_components.freebox_ultra_ultimate.api import EndpointUnavailable, FreeboxError, PermissionDenied
from custom_components.freebox_ultra_ultimate.collectors import Collectors
from custom_components.freebox_ultra_ultimate.privacy import strip_secrets


async def test_endpoint_failure_is_isolated(api_mock, options):
    options["families"] = ["wan", "fibre", "system"]
    original = api_mock.get.side_effect

    async def get(path):
        if path == "connection/ftth/":
            raise EndpointUnavailable("nodev", 404)
        return await original(path)

    api_mock.get.side_effect = get
    collectors = Collectors(api_mock)
    await collectors.update(options)
    assert collectors.healthy("connection/") and collectors.healthy("system/")
    assert collectors.capabilities["connection/ftth/"].status == "unsupported"
    calls = api_mock.get.call_count
    await collectors.fetch("connection/ftth/", "object", "fibre")
    assert api_mock.get.call_count == calls


async def test_permission_rejection_does_not_break_lan(api_mock, options):
    options["families"] = ["presence", "downloads"]
    original = api_mock.get.side_effect

    async def get(path):
        if path.startswith("downloads/"):
            raise PermissionDenied("insufficient_rights", 403)
        return await original(path)

    api_mock.get.side_effect = get
    collectors = Collectors(api_mock)
    await collectors.update(options)
    assert collectors.healthy("lan/browser/pub/")
    assert collectors.capabilities["downloads/"].status == "forbidden"


async def test_shapes_validated_before_snapshot(api_mock):
    api_mock.get = AsyncMock(return_value={"wrong": "shape"})
    collectors = Collectors(api_mock)
    assert await collectors.fetch("wifi/ap/", "list", "wifi_radios") is None
    assert collectors.capabilities["wifi/ap/"].error == "invalid_shape"


async def test_one_ap_discovery_per_cycle(api_mock, options):
    options["families"] = ["wifi_clients", "wifi_radios"]
    collectors = Collectors(api_mock)
    await collectors.update(options)
    assert sum(call.args == ("wifi/ap/",) for call in api_mock.get.call_args_list) == 1


async def test_timeout_preserves_last_snapshot_but_marks_unavailable(api_mock):
    collectors = Collectors(api_mock)
    await collectors.fetch("connection/", "object", "wan")
    api_mock.get.side_effect = FreeboxError("transport_error")
    assert await collectors.fetch("connection/", "object", "wan") is None
    assert "connection/" in collectors.snapshots and not collectors.healthy("connection/")


def test_secret_stripping_is_recursive():
    assert strip_secrets({"config": {"key": "secret", "ssid": "visible"}, "app_token": "secret"}) == {
        "config": {"ssid": "visible"}
    }
