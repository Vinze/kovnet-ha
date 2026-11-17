"""'Opvang vandaag' binary sensor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.util import dt as dt_util

from .entity import KovnetTimeEntity, fmt_time


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(KovnetCareToday(coordinator, cid) for cid in coordinator.data.schedules)


class KovnetCareToday(KovnetTimeEntity, BinarySensorEntity):
    _attr_translation_key = "care_today"
    _attr_icon = "mdi:human-child"

    def __init__(self, coordinator, contract_id):
        super().__init__(coordinator, contract_id, "care_today")

    @property
    def _today(self):
        schedule = self.schedule
        return schedule.days.get(dt_util.now().date()) if schedule else None

    @property
    def is_on(self) -> bool:
        return bool(self._today and self._today.has_care)

    @property
    def extra_state_attributes(self):
        d = self._today
        if d is None:
            return {}
        return {
            "start": fmt_time(d.start),
            "eind": fmt_time(d.end),
            "groep": ", ".join(d.groups) or None,
            "afgemeld": d.cancelled,
            "in_afwachting": d.pending,
            "gesloten": d.closed,
            "opmerking": d.remarks or None,
        }
