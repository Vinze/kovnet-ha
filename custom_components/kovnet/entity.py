"""Base entity + helpers."""
from __future__ import annotations

from datetime import date, datetime, time

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import CareDay, Roster
from .const import DOMAIN
from .coordinator import KovnetCoordinator


def local_dt(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tzinfo=dt_util.get_default_time_zone())


def care_days(roster: Roster | None) -> list[CareDay]:
    if roster is None:
        return []
    return [d for _, d in sorted(roster.days.items())]


class KovnetEntity(CoordinatorEntity[KovnetCoordinator]):
    """One entity for one contract (= one child)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KovnetCoordinator, contract_id: int, key: str) -> None:
        super().__init__(coordinator)
        self.contract_id = contract_id
        self._attr_unique_id = f"{contract_id}_{key}"
        child = self.roster.child_name if self.roster else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(contract_id))},
            name=f"KOVnet {child or contract_id}",
            manufacturer="KOVnet",
            model="Opvangcontract",
            configuration_url="https://app.kovnet.nl/",
        )

    @property
    def roster(self) -> Roster | None:
        return self.coordinator.data.rosters.get(self.contract_id)

    @property
    def available(self) -> bool:
        return super().available and self.roster is not None


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
