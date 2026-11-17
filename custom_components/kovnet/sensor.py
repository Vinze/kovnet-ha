"""'Volgende opvang' timestamp sensor."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import CareDay
from .coordinator import KovnetConfigEntry, KovnetCoordinator
from .entity import KovnetTimeEntity, care_days, local_dt


PARALLEL_UPDATES = 0  # the coordinator does all fetching


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KovnetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(KovnetNextCare(coordinator, cid) for cid in coordinator.data.schedules)


class KovnetNextCare(KovnetTimeEntity, SensorEntity):
    _attr_translation_key = "next_care"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: KovnetCoordinator, contract_id: int) -> None:
        super().__init__(coordinator, contract_id, "next_care")

    def _next(self) -> CareDay | None:
        now = dt_util.now()
        for d in care_days(self.schedule):
            if d.has_care and local_dt(d.day, d.start) > now:
                return d
        return None

    @property
    def native_value(self) -> datetime | None:
        d = self._next()
        return local_dt(d.day, d.start) if d else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._next()
        if d is None:
            return {}
        return {"eind": local_dt(d.day, d.end).isoformat(), "groep": ", ".join(d.groups)}
