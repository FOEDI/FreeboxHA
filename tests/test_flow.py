from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.freebox_ultra_ultimate.const import DOMAIN


async def start_pairing(hass, api_mock):
    api_mock.authorize = AsyncMock(return_value=("pair-secret", 42))
    api_mock.authorization_status = AsyncMock(return_value="granted")
    with (
        patch("custom_components.freebox_ultra_ultimate.config_flow.FreeboxClient", return_value=api_mock),
        patch("custom_components.freebox_ultra_ultimate.async_setup_entry", return_value=False),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.0.2.254", "port": 443})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"]["app_token"] == "pair-secret"
        assert result["result"].unique_id == "test-box"
        return result


async def test_graphical_pairing(hass, api_mock):
    await start_pairing(hass, api_mock)


async def test_zeroconf_starts_graphical_confirmation(hass):
    info = ZeroconfServiceInfo(
        ip_address="192.0.2.254",
        ip_addresses=["192.0.2.254"],
        hostname="box.local.",
        name="Freebox._fbx-api._tcp.local.",
        port=80,
        type="_fbx-api._tcp.local.",
        properties={"uid": "test-box"},
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "zeroconf"}, data=info)
    assert result["type"] == FlowResultType.FORM and result["step_id"] == "user"
    assert result["data_schema"]({"host": "192.0.2.254", "port": 443})["host"] == "192.0.2.254"


async def test_duplicate_uid_is_rejected(hass, api_mock, entry):
    entry.add_to_hass(hass)
    with patch("custom_components.freebox_ultra_ultimate.config_flow.FreeboxClient", return_value=api_mock):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={"host": "192.0.2.254", "port": 443}
        )
        assert result["type"] == FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_pairing_denied(hass, api_mock):
    api_mock.authorize = AsyncMock(return_value=("pair-secret", 42))
    api_mock.authorization_status = AsyncMock(return_value="denied")
    with patch("custom_components.freebox_ultra_ultimate.config_flow.FreeboxClient", return_value=api_mock):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={"host": "192.0.2.254", "port": 443}
        )
        if result["type"] == FlowResultType.SHOW_PROGRESS_DONE:
            result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["type"] == FlowResultType.ABORT and result["reason"] == "denied"


async def test_options_preserve_other_settings(hass, entry):
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "categories"})
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"families": ["wan"], "detailed_devices": True, "websocket": False}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["families"] == ["wan"]
    assert entry.options["interval_wan"] == 10 and entry.options["disconnect_delay"] == 40


async def test_certificate_failure_has_specific_safe_error(hass, api_mock, caplog):
    from custom_components.freebox_ultra_ultimate.api import FreeboxError

    api_mock.discover.side_effect = FreeboxError("tls_certificate_error")
    api_mock.authorize = AsyncMock()
    with patch("custom_components.freebox_ultra_ultimate.config_flow.FreeboxClient", return_value=api_mock):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={"host": "192.0.2.254", "port": 443}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "tls_certificate_error"}
    assert "stage=discovery code=tls_certificate_error" in caplog.text
    assert "192.0.2.254" not in caplog.text
    api_mock.authorize.assert_not_called()


async def test_pairing_application_id_fits_freebox_limit(hass, api_mock):
    result = await start_pairing(hass, api_mock)
    app_id = api_mock.authorize.call_args.args[0]
    assert len(app_id) <= 32
    assert result["data"]["app_id"] == app_id
    assert app_id.startswith("fr.freeboxha.")
