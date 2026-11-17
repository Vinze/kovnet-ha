"""Repairs for KOVnet: log in again before a 2FA token expires."""
from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult


class TokenExpiringFlow(RepairsFlow):
    """Confirm, then start the normal re-authentication flow."""

    def __init__(self, entry_id: str | None) -> None:
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self._entry_id or "")
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        if user_input is not None:
            entry.async_start_reauth(self.hass)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm", description_placeholders={"title": entry.title}
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    return TokenExpiringFlow((data or {}).get("entry_id"))
