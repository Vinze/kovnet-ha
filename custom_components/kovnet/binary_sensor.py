"""'Opvang vandaag' binary sensor."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import CareDay
from .coordinator import KovnetConfigEntry, KovnetCoordinator
from .entity import KovnetTimeEntity, fmt_time


PARALLEL_UPDATES = 0  # the coordinator does all fetching


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KovnetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(KovnetCareToday(coordinator, cid) for cid in coordinator.data.schedules)


class KovnetCareToday(KovnetTimeEntity, BinarySensorEntity):
    _attr_translation_key = "care_today"
    _attr_icon = "mdi:human-child"

    def __init__(self, coordinator: KovnetCoordinator, contract_id: int) -> None:
        super().__init__(coordinator, contract_id, "care_today")

    @property
    def _today(self) -> CareDay | None:
        schedule = self.schedule
        return schedule.days.get(dt_util.now().date()) if schedule else None

    @property
    def is_on(self) -> bool:
        return bool(self._today and self._today.has_care)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
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
