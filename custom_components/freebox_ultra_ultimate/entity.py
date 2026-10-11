"""Shared dynamic entity discovery and endpoint-specific availability."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.device_registry import async_get as get_device_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FreeboxCoordinator
from .metrics import Metric


class FreeboxEntity(CoordinatorEntity[FreeboxCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: FreeboxCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.key = key
        metric = coordinator.model.metrics[key]
        self._attr_name = metric.name
        uid = coordinator.api.version.uid if coordinator.api.version else coordinator.config_entry.entry_id
        self._attr_unique_id = f"{uid}:{key}"
        self._device_key = metric.device
        self._attr_entity_registry_enabled_default = metric.enabled
        self._attr_entity_category = EntityCategory.DIAGNOSTIC if metric.diagnostic else None
        coordinator.registered(self._attr_unique_id)

    @property
    def metric(self) -> Metric | None:
        return self.coordinator.model.metrics.get(self.key)

    @property
    def available(self) -> bool:
        metric = self.metric
        return bool(
            metric is not None
            and (metric.cached or super().available)
            and (metric.cached or not metric.endpoint or self.coordinator.collectors.healthy(metric.endpoint))
            and metric.value is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        uid = (
            self.coordinator.api.version.uid if self.coordinator.api.version else self.coordinator.config_entry.entry_id
        )
        device = self.coordinator.model.devices.get(self._device_key)
        result = DeviceInfo(identifiers={(DOMAIN, f"{uid}:{self._device_key}")})
        if device:
            result.update(name=device.name, manufacturer=device.manufacturer)
            if device.model:
                result["model"] = device.model
            if device.firmware:
                result["sw_version"] = device.firmware
            if device.hardware:
                result["hw_version"] = device.hardware
            if device.parent:
                parent = get_device_registry(self.coordinator.hass).async_get_device_by_identifier(
                    (DOMAIN, f"{uid}:{device.parent}"), self.coordinator.config_entry.entry_id
                )
                if parent:
                    result["via_device_id"] = parent.id
        # Integration-scoped identity avoids HA 2026.10 moving devices shared by other integrations.
        return result

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.metric.attributes if self.metric and self.metric.attributes else None


async def setup_dynamic(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback, platform: str, entity_class: Any
) -> None:
    coordinator: FreeboxCoordinator = entry.runtime_data
    seen: set[str] = set()

    @callback
    def discover() -> None:
        consolidate_devices(hass, entry, coordinator)
        entities = []
        for key, metric in coordinator.model.metrics.items():
            if metric.platform == platform and key not in seen:
                seen.add(key)
                entities.append(entity_class(coordinator, key))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


@callback
def consolidate_devices(hass: HomeAssistant, entry: ConfigEntry, coordinator: FreeboxCoordinator) -> None:
    """Remove only this integration's superseded aliases after successful grouping."""
    if not coordinator.inventory.group_by_name or coordinator.api.version is None:
        return
    uid = coordinator.api.version.uid
    registry = er.async_get(hass)
    devices = get_device_registry(hass)
    for alias, canonical in coordinator.inventory.aliases.items():
        if alias == canonical or alias in coordinator.cleaned_aliases:
            continue
        prefix = f"{uid}:{alias}:"
        for item in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
            if item.platform == DOMAIN and item.unique_id.startswith(prefix):
                registry.async_remove(item.entity_id)
        old = devices.async_get_device_by_identifier((DOMAIN, f"{uid}:{alias}"), entry.entry_id)
        if old:
            devices.async_remove_device(old.id)
        coordinator.cleaned_aliases.add(alias)


@callback
def apply_entity_defaults(hass: HomeAssistant, entry: ConfigEntry, coordinator: FreeboxCoordinator) -> None:
    """Apply a requested profile once, retaining entities explicitly disabled by users."""
    if not entry.options.get("apply_entity_defaults", False) or coordinator.api.version is None:
        return
    prefix = f"{coordinator.api.version.uid}:"
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.platform != DOMAIN or not item.unique_id.startswith(prefix):
            continue
        metric = coordinator.model.metrics.get(item.unique_id[len(prefix) :])
        enabled = (
            metric.enabled
            if metric
            else item.unique_id[len(prefix) :].startswith("event:") and coordinator.options["advanced_metrics"]
        )
        if item.disabled_by in {None, er.RegistryEntryDisabler.INTEGRATION}:
            desired = None if enabled else er.RegistryEntryDisabler.INTEGRATION
            if item.disabled_by != desired:
                registry.async_update_entity(item.entity_id, disabled_by=desired)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "apply_entity_defaults": False})
