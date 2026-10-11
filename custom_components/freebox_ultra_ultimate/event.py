"""Event entities complement the documented Home Assistant bus events."""

from homeassistant.components.event import EventEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, EVENT_PREFIX, EVENT_TYPES


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(FreeboxEvent(coordinator, kind) for kind in EVENT_TYPES)


class FreeboxEvent(EventEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, kind):
        self.coordinator = coordinator
        self._attr_entity_registry_enabled_default = coordinator.options["advanced_metrics"]
        self.kind = EVENT_PREFIX + kind
        self._attr_name = kind.replace("_", " ")
        self._attr_event_types = [self.kind]
        self._attr_unique_id = f"{coordinator.api.version.uid}:event:{kind}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{coordinator.api.version.uid}:box")})
        coordinator.registered(self._attr_unique_id)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.subscribe_events(self._event))

    @callback
    def _event(self, event):
        if event["event_type"] == self.kind:
            self._trigger_event(self.kind, {key: value for key, value in event.items() if key != "event_type"})
            self.async_write_ha_state()
