"""KOVnet integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KovnetApi
from .const import CONF_CONTRACT_ID, CONF_CONTRACT_IDS, CONF_TOKEN, PLATFORMS
from .coordinator import KovnetCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = KovnetApi(async_get_clientsession(hass), entry.data.get(CONF_TOKEN))
    coordinator = KovnetCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """v1 (web scraping, one contract per entry) -> v2 (app API).

    No token yet: the first refresh logs in with the stored password. The
    contract stays the only one for this entry, so entity IDs are unchanged.
    """
    if entry.version == 1:
        data = {
            CONF_EMAIL: entry.data[CONF_EMAIL],
            CONF_PASSWORD: entry.data[CONF_PASSWORD],
            CONF_CONTRACT_IDS: [int(entry.data[CONF_CONTRACT_ID])],
        }
        hass.config_entries.async_update_entry(entry, data=data, version=2)
        _LOGGER.info("KOVnet entry %s migrated to version 2 (app API)", entry.title)
    return True
