"""KOVnet integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KovnetApi
from .const import (
    CONF_CONTRACT_ID,
    CONF_CONTRACT_IDS,
    CONF_TOKEN,
    CONF_TWO_FACTOR,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import KovnetConfigEntry, KovnetCoordinator, token_issue_id

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: KovnetConfigEntry) -> bool:
    api = KovnetApi(async_get_clientsession(hass), entry.data.get(CONF_TOKEN))
    coordinator = KovnetCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _remove_stale_devices(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KovnetConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: KovnetConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, token_issue_id(entry.entry_id))


def _remove_stale_devices(hass: HomeAssistant, entry: KovnetConfigEntry) -> None:
    """Remove devices of contracts that are no longer selected (reconfigure)."""
    selected = {str(cid) for cid in entry.data.get(CONF_CONTRACT_IDS) or []}
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        ids = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if ids and not ids & selected:
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older config entries.

    1   -> 2.1: web scraping, one contract per entry -> app API. No token yet: the
                first refresh logs in with the stored password. The contract stays
                the only one for this entry, so entity IDs are unchanged.
    2.1 -> 2.2: no stored password for tokens from a 2FA login (never used).
    """
    if entry.version > 2:
        return False
    if entry.version == 1:
        data = {
            CONF_EMAIL: entry.data[CONF_EMAIL],
            CONF_PASSWORD: entry.data[CONF_PASSWORD],
            CONF_CONTRACT_IDS: [int(entry.data[CONF_CONTRACT_ID])],
        }
        hass.config_entries.async_update_entry(entry, data=data, version=2, minor_version=1)
        _LOGGER.info("KOVnet entry %s migrated to version 2 (app API)", entry.title)
    if entry.minor_version < 2:
        data = dict(entry.data)
        if data.get(CONF_TWO_FACTOR):
            data.pop(CONF_PASSWORD, None)
        hass.config_entries.async_update_entry(entry, data=data, minor_version=2)
    return True
