"""Data coordinator for KOVnet."""
from __future__ import annotations

from dataclasses import dataclass
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    KovnetApi,
    KovnetAuthError,
    KovnetError,
    KovnetTwoFactorRequired,
    KovnetUser,
    Profile,
    Roster,
)
from .const import (
    CONF_CONTRACT_IDS,
    CONF_TOKEN,
    CONF_TWO_FACTOR,
    CONF_USER_ID,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class KovnetData:
    profile: Profile
    rosters: dict[int, Roster]


def pick_user(users: list[KovnetUser], user_id: int | None) -> KovnetUser:
    return next((u for u in users if user_id is not None and u.user_id == user_id), users[0])


class KovnetCoordinator(DataUpdateCoordinator[KovnetData]):
    """Fetches profile + this month and next month for every selected contract."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: KovnetApi) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL, config_entry=entry
        )
        self.api = api

    async def _async_update_data(self) -> KovnetData:
        try:
            try:
                return await self._fetch()
            except KovnetAuthError:
                if not await self._relogin():
                    raise
                return await self._fetch()
        except KovnetTwoFactorRequired as err:
            raise ConfigEntryAuthFailed(
                "KOVnet vraagt een verificatiecode; log opnieuw in via de melding"
            ) from err
        except KovnetAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (KovnetError, aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(str(err)) from err

    async def _relogin(self) -> bool:
        """Token invalid: try a silent login with the stored password (works without 2FA).

        Skipped when the token came from a 2FA login: the attempt would only make
        KOVnet mail a code that is useless, because the reauth flow logs in (and
        mails a code) again.
        """
        entry = self.config_entry
        password = entry.data.get(CONF_PASSWORD)
        if not password or entry.data.get(CONF_TWO_FACTOR):
            return False
        _LOGGER.debug("KOVnet token rejected, logging in again")
        users = await self.api.login(entry.data[CONF_EMAIL], password)
        user = pick_user(users, entry.data.get(CONF_USER_ID))
        self.api.token = user.token
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: user.token, CONF_USER_ID: user.user_id}
        )
        return True

    async def _fetch(self) -> KovnetData:
        profile = await self.api.profile()
        today = dt_util.now().date()
        months = [
            (today.year, today.month),
            (today.year + (today.month == 12), today.month % 12 + 1),
        ]
        selected = self.config_entry.data.get(CONF_CONTRACT_IDS)
        if selected:
            ids = [int(cid) for cid in selected if int(cid) in profile.contracts]
        else:
            ids = [cid for cid, c in profile.contracts.items() if c.is_current(today)]

        rosters: dict[int, Roster] = {}
        for cid in ids:
            days = {}
            for year, month in months:
                days.update(await self.api.schedule(cid, year, month, profile.group_names))
            rosters[cid] = Roster(child_name=profile.contracts[cid].child_name, days=days)
        return KovnetData(profile=profile, rosters=rosters)
