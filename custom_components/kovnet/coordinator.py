"""Data coordinator for KOVnet."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    CareDay,
    KovnetApi,
    KovnetAuthError,
    KovnetError,
    KovnetTwoFactorRequired,
    KovnetUser,
    Profile,
    Schedule,
)
from .const import (
    CONF_CONTRACT_IDS,
    CONF_TOKEN,
    CONF_TWO_FACTOR,
    CONF_USER_ID,
    DOMAIN,
    UPDATE_INTERVAL,
)

# Always this month and the next; one more when those hold no upcoming care
# (e.g. a long summer closing), so "Volgende opvang" does not go empty.
MIN_MONTHS = 2
MAX_MONTHS = 3

_LOGGER = logging.getLogger(__name__)


@dataclass
class KovnetData:
    profile: Profile
    schedules: dict[int, Schedule]


def pick_user(users: list[KovnetUser], user_id: int | None) -> KovnetUser:
    return next((u for u in users if user_id is not None and u.user_id == user_id), users[0])


async def async_pick_user(
    hass: HomeAssistant, users: list[KovnetUser], data: Mapping[str, Any]
) -> KovnetUser:
    """Pick the account of an existing entry.

    Entries migrated from v1 have no user_id; with accounts at several
    organisations, pick the one whose profile holds the entry's contracts.
    """
    user_id = data.get(CONF_USER_ID)
    if user_id is not None or len(users) == 1:
        return pick_user(users, user_id)
    wanted = {int(cid) for cid in data.get(CONF_CONTRACT_IDS) or []}
    session = async_get_clientsession(hass)
    for user in users:
        try:
            profile = await KovnetApi(session, user.token).profile()
        except (KovnetError, aiohttp.ClientError, TimeoutError):
            continue
        if wanted & profile.contracts.keys():
            return user
    return users[0]


def login_data(
    data: Mapping[str, Any], user: KovnetUser, password: str, two_factor: bool
) -> dict[str, Any]:
    """Entry data after a login.

    The password is only kept for the silent re-login, which is never done for a
    token from a 2FA login (see KovnetCoordinator._relogin), so then drop it.
    """
    new = {
        **data,
        CONF_TOKEN: user.token,
        CONF_USER_ID: user.user_id,
        CONF_TWO_FACTOR: two_factor,
        CONF_PASSWORD: password,
    }
    if two_factor:
        new.pop(CONF_PASSWORD)
    return new


def months_from(today: date) -> Iterator[tuple[int, int]]:
    year, month = today.year, today.month
    while True:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


class KovnetCoordinator(DataUpdateCoordinator[KovnetData]):
    """Fetches profile + this month and the next (or one more) for every selected contract."""

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
        user = await async_pick_user(self.hass, users, entry.data)
        self.api.token = user.token
        self.hass.config_entries.async_update_entry(
            entry, data=login_data(entry.data, user, password, two_factor=False)
        )
        return True

    async def _fetch(self) -> KovnetData:
        profile = await self.api.profile()
        today = dt_util.now().date()
        selected = self.config_entry.data.get(CONF_CONTRACT_IDS)
        if selected:
            ids = [int(cid) for cid in selected if int(cid) in profile.contracts]
        else:
            ids = [cid for cid, c in profile.contracts.items() if c.is_current(today)]

        schedules: dict[int, Schedule] = {}
        for cid in ids:
            days: dict[date, CareDay] = {}
            for i, (year, month) in enumerate(months_from(today)):
                if i == MAX_MONTHS or (
                    i >= MIN_MONTHS
                    and any(d.has_care and d.day >= today for d in days.values())
                ):
                    break
                days.update(await self.api.schedule(cid, year, month, profile.group_names))
            schedules[cid] = Schedule(child_name=profile.contracts[cid].child_name, days=days)
        return KovnetData(profile=profile, schedules=schedules)
