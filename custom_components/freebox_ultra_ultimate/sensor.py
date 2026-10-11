"""Scalar sensors with verified units and Recorder statistics metadata."""

from homeassistant.components.sensor import SensorEntity

from .entity import FreeboxEntity, setup_dynamic


async def async_setup_entry(hass, entry, async_add_entities):
    await setup_dynamic(hass, entry, async_add_entities, "sensor", FreeboxSensor)


class FreeboxSensor(FreeboxEntity, SensorEntity):
    @property
    def native_value(self):
        return self.metric.value if self.metric else None

    @property
    def native_unit_of_measurement(self):
        return self.metric.unit if self.metric else None

    @property
    def device_class(self):
        return self.metric.device_class if self.metric else None

    @property
    def state_class(self):
        return self.metric.state_class if self.metric else None
