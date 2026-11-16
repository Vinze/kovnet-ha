"""'Volgende opvang' timestamp sensor."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.util import dt as dt_util

from .entity import KovnetTimeEntity, care_days, local_dt


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(KovnetNextCare(coordinator, cid) for cid in coordinator.data.schedules)


class KovnetNextCare(KovnetTimeEntity, SensorEntity):
    _attr_name = "Volgende opvang"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, contract_id):
        super().__init__(coordinator, contract_id, "next_care")

    def _next(self):
        now = dt_util.now()
        for d in care_days(self.schedule):
            if d.has_care and local_dt(d.day, d.start) > now:
                return d
        return None

    @property
    def native_value(self):
        d = self._next()
        return local_dt(d.day, d.start) if d else None

    @property
    def extra_state_attributes(self):
        d = self._next()
        if d is None:
            return {}
        return {"eind": local_dt(d.day, d.end).isoformat(), "groep": ", ".join(d.groups)}
