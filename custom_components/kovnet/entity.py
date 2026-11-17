"""Base entity + helpers."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import END_OF_DAY, CareDay, Schedule
from .const import DOMAIN
from .coordinator import KovnetCoordinator


def local_dt(day: date, t: time) -> datetime:
    """Local datetime; END_OF_DAY ("24:00") becomes midnight of the next day."""
    if t == END_OF_DAY:
        day, t = day + timedelta(days=1), time(0)
    return datetime.combine(day, t, tzinfo=dt_util.get_default_time_zone())


def fmt_time(t: time | None) -> str | None:
    if t is None:
        return None
    return "24:00" if t == END_OF_DAY else t.strftime("%H:%M")


def care_days(schedule: Schedule | None) -> list[CareDay]:
    if schedule is None:
        return []
    return [d for _, d in sorted(schedule.days.items())]


class KovnetEntity(CoordinatorEntity[KovnetCoordinator]):
    """One entity for one contract (= one child)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KovnetCoordinator, contract_id: int, key: str) -> None:
        super().__init__(coordinator)
        self.contract_id = contract_id
        self._attr_unique_id = f"{contract_id}_{key}"
        child = self.schedule.child_name if self.schedule else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(contract_id))},
            name=f"KOVnet {child or contract_id}",
            manufacturer="KOVnet",
            model="Opvangcontract",
            configuration_url="https://app.kovnet.nl/",
        )

    @property
    def schedule(self) -> Schedule | None:
        return self.coordinator.data.schedules.get(self.contract_id)

    @property
    def available(self) -> bool:
        return super().available and self.schedule is not None


class KovnetTimeEntity(KovnetEntity):
    """Entity whose state depends on the clock: re-evaluate every minute.

    The coordinator only polls hourly; without this, 'today'/'next' values
    would lag up to an hour behind (e.g. just after midnight).
    """

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(self.hass, self._async_tick, second=0)
        )

    @callback
    def _async_tick(self, _now: datetime) -> None:
        self.async_write_ha_state()
