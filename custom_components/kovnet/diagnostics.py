"""Diagnostics for KOVnet (no names, e-mail, password, token or remarks)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .api import CareDay, token_expiry
from .const import CONF_TOKEN
from .coordinator import KovnetConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN}


def _day(d: CareDay) -> dict[str, Any]:
    return {
        "day": d.day.isoformat(),
        "closed": d.closed,
        "blocks": [
            {
                "group_id": b.group_id,
                "start": b.start.isoformat(),
                "end": b.end.isoformat(),
                "cancelled": b.cancelled,
                "pending": b.pending,
                "has_remarks": bool(b.remarks),
            }
            for b in d.blocks
        ],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KovnetConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    expiry = token_expiry(coordinator.api.token)
    return {
        "entry": {
            "version": f"{entry.version}.{entry.minor_version}",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "token_expiry": expiry.isoformat() if expiry else None,
        "last_update_success": coordinator.last_update_success,
        "contracts": {
            cid: {
                "start": c.start.isoformat() if c.start else None,
                "end": c.end.isoformat() if c.end else None,
                "archive": c.archive,
            }
            for cid, c in data.profile.contracts.items()
        },
        "group_ids": sorted(data.profile.group_names),
        "schedules": {
            cid: [_day(d) for _, d in sorted(s.days.items()) if d.blocks or d.closed]
            for cid, s in data.schedules.items()
        },
    }
