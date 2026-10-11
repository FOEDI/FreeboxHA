"""Presence, link, service and hardware state entities."""

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import FreeboxEntity, setup_dynamic


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_dynamic(hass, entry, async_add_entities, "binary_sensor", FreeboxBinarySensor)


class FreeboxBinarySensor(FreeboxEntity, BinarySensorEntity):
    @property
    def is_on(self):
        return self.metric.value if self.metric and isinstance(self.metric.value, bool) else None

    @property
    def device_class(self):
        return self.metric.device_class if self.metric else None
