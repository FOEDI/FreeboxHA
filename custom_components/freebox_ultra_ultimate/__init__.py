"""Freebox HA: local, read-only network and hardware monitoring."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, FreeboxClient, FreeboxError, tls_context
from .const import DEFAULT_OPTIONS, DOMAIN, PLATFORMS
from .coordinator import FreeboxCoordinator
from .entity import apply_entity_defaults, consolidate_devices


def create_client(hass: HomeAssistant, entry: ConfigEntry, context) -> FreeboxClient:
    return FreeboxClient(
        async_get_clientsession(hass),
        context,
        host=entry.data["host"],
        port=entry.data.get("port", 443),
        app_id=entry.data["app_id"],
        app_token=entry.data["app_token"],
        expected_uid=entry.unique_id,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    context = await hass.async_add_executor_job(tls_context)
    api = create_client(hass, entry, context)
    try:
        await api.discover()
        await api.login()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(err.code) from err
    except FreeboxError as err:
        raise ConfigEntryNotReady(err.code) from err
    coordinator = FreeboxCoordinator(hass, entry, api)
    await coordinator.restore()
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        root = coordinator.model.devices["box"]
        assert api.version is not None
        dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{api.version.uid}:box")},
            name=root.name,
            manufacturer=root.manufacturer,
            model=root.model,
            sw_version=root.firmware,
            hw_version=root.hardware,
        )
        consolidate_devices(hass, entry, coordinator)
        apply_entity_defaults(hass, entry, coordinator)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.stop()
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    coordinator.start_websocket()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.stop()
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Move the initial exhaustive defaults to the requested essential profile."""
    if entry.version != 1:
        return False
    if entry.minor_version < 2:
        options = {
            **entry.options,
            "advanced_metrics": False,
            "detailed_devices": False,
            "group_by_name": True,
            "apply_entity_defaults": True,
        }
        legacy_families = {
            "wan",
            "fibre",
            "presence",
            "wifi_clients",
            "ethernet",
            "system",
            "wifi_radios",
            "dhcp",
            "network",
            "storage",
            "services",
            "routing",
            "vpn",
            "freeplug",
        }
        if "families" not in options or set(options["families"]) == legacy_families:
            options["families"] = list(DEFAULT_OPTIONS["families"])
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    return True
