"""KOVnet calendar."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .api import CareDay
from .entity import KovnetEntity, care_days, local_dt


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(KovnetCalendar(coordinator, cid) for cid in coordinator.data.rosters)


def _to_event(d: CareDay) -> CalendarEvent | None:
    if d.has_care:
        return CalendarEvent(
            start=local_dt(d.day, d.start),
            end=local_dt(d.day, d.end),
            summary=f"Opvang {', '.join(d.groups)}".strip(),
            description=d.remarks or None,
        )
    if d.cancelled or d.closed:
        return CalendarEvent(
            start=d.day,
            end=d.day + timedelta(days=1),
            summary="Opvang gesloten" if d.closed else "Opvang afgemeld",
            description=d.remarks or None,
        )
    return None


class KovnetCalendar(KovnetEntity, CalendarEntity):
    _attr_name = "Opvang"

    def __init__(self, coordinator, contract_id):
        super().__init__(coordinator, contract_id, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        # Only real care blocks, so the entity state is 'on' exactly during opvang.
        now = dt_util.now()
        for d in care_days(self.roster):
            if d.has_care and local_dt(d.day, d.end) > now:
                return _to_event(d)
        return None

    async def async_get_events(self, hass, start_date: datetime, end_date: datetime):
        events = []
        for d in care_days(self.roster):
            ev = _to_event(d)
            if ev is None:
                continue
            ev_start, ev_end = ev.start_datetime_local, ev.end_datetime_local
            if ev_end > start_date and ev_start < end_date:
                events.append(ev)
        return events
