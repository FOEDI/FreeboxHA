"""Router device tracking using stable scoped network identities."""

from homeassistant.components.device_tracker import BaseScannerEntity, SourceType

from .entity import FreeboxEntity, setup_dynamic


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_dynamic(hass, entry, async_add_entities, "device_tracker", FreeboxTracker)


class FreeboxTracker(FreeboxEntity, BaseScannerEntity):
    _attr_source_type = SourceType.ROUTER

    @property
    def is_connected(self):
        return bool(self.metric.value) if self.metric else False

    @property
    def ip_address(self):
        device = self.coordinator.inventory.devices.get(self._device_key)
        return device.ipv4[0] if device and device.ipv4 and self.coordinator.options["expose_identity"] else None

    @property
    def hostname(self):
        device = self.coordinator.inventory.devices.get(self._device_key)
        return device.name if device and self.coordinator.options["expose_identity"] else None
