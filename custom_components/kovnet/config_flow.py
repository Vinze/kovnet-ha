"""Config flow for KOVnet (app API, optional e-mailed 2FA code)."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)
from homeassistant.util import dt as dt_util

from .api import (
    KovnetApi,
    KovnetAuthError,
    KovnetError,
    KovnetInvalidCode,
    KovnetTwoFactorRequired,
    KovnetUser,
    Profile,
)
from .const import (
    CONF_CODE,
    CONF_CONTRACT_IDS,
    CONF_RESEND,
    CONF_TOKEN,
    CONF_USER_ID,
    DOMAIN,
)
from .coordinator import async_pick_user, login_data

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})
CODE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CODE, default=""): str,
        vol.Optional(CONF_RESEND, default=False): bool,
    }
)
PASSWORD_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class KovnetConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._users: list[KovnetUser] = []
        self._user: KovnetUser | None = None
        self._profile: Profile | None = None
        self._two_factor = False

    def _api(self, token: str | None = None) -> KovnetApi:
        return KovnetApi(async_get_clientsession(self.hass), token)

    async def _login(self, code: str | None = None) -> str | None:
        """Log in; returns an error key, 'need_code', or None on success."""
        try:
            self._users = await self._api().login(self._email, self._password, code)
        except KovnetTwoFactorRequired:
            return "need_code"
        except KovnetInvalidCode:
            return "invalid_code"
        except KovnetAuthError:
            return "invalid_auth"
        except (KovnetError, aiohttp.ClientError, TimeoutError):
            _LOGGER.exception("KOVnet login failed")
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during KOVnet login")
            return "unknown"
        self._two_factor = code is not None
        return None

    async def _after_login(self) -> ConfigFlowResult:
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            user = await async_pick_user(self.hass, self._users, entry.data)
            return self.async_update_reload_and_abort(
                entry, data=login_data(entry.data, user, self._password, self._two_factor)
            )
        if len(self._users) > 1:
            return await self.async_step_account()
        self._user = self._users[0]
        return await self.async_step_contracts()

    # --- initial setup -------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            self._password = user_input[CONF_PASSWORD]
            error = await self._login()
            if error == "need_code":
                return await self.async_step_code()
            if error is None:
                return await self._after_login()
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, {CONF_EMAIL: self._email} if self._email else None
            ),
            errors=errors,
        )

    async def async_step_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            code = user_input.get(CONF_CODE, "").strip()
            if user_input.get(CONF_RESEND):
                # A login without code makes KOVnet mail a fresh code.
                error = await self._login()
                if error is None:  # 2FA was switched off in the meantime
                    return await self._after_login()
                errors["base"] = "code_resent" if error == "need_code" else error
            elif not code:
                errors["base"] = "invalid_code"
            else:
                error = await self._login(code)
                if error is None:
                    return await self._after_login()
                errors["base"] = (
                    "invalid_code" if error in ("need_code", "invalid_auth") else error
                )
        return self.async_show_form(
            step_id="code",
            data_schema=CODE_SCHEMA,
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            idx = int(user_input[CONF_USER_ID])
            self._user = self._users[idx]
            return await self.async_step_contracts()
        options = [
            SelectOptionDict(value=str(i), label=u.organization or f"Account {u.user_id}")
            for i, u in enumerate(self._users)
        ]
        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {vol.Required(CONF_USER_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    async def async_step_contracts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._user is not None
        errors: dict[str, str] = {}
        if self._profile is None:
            try:
                self._profile = await self._api(self._user.token).profile()
            except (KovnetError, aiohttp.ClientError, TimeoutError):
                _LOGGER.exception("Could not load KOVnet profile")
                return self.async_abort(reason="cannot_connect")

        if self._user.user_id is not None:
            unique_id = str(self._user.user_id)
        else:
            unique_id = f"{self._email.lower()}|{self._user.organization or ''}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Entries migrated from v1 have a different unique_id (one entry per
        # contract), so also leave out contracts that another entry already shows.
        configured = self._configured_contracts(self._email)
        today = dt_util.now().date()
        current = {
            cid: c for cid, c in self._profile.contracts.items() if c.is_current(today)
        }
        if not current:
            return self.async_abort(reason="no_contracts")
        contracts = {str(cid): c.label for cid, c in current.items() if cid not in configured}
        if not contracts:
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            chosen = [int(cid) for cid in user_input[CONF_CONTRACT_IDS]]
            if not chosen:
                errors["base"] = "no_contract_selected"
            else:
                return self.async_create_entry(
                    title=self._user.organization or "KOVnet",
                    data=login_data(
                        {CONF_EMAIL: self._email, CONF_CONTRACT_IDS: chosen},
                        self._user,
                        self._password,
                        self._two_factor,
                    ),
                )
        return self.async_show_form(
            step_id="contracts",
            data_schema=_contracts_schema(contracts, list(contracts)),
            errors=errors,
        )

    def _configured_contracts(self, email: str, exclude: ConfigEntry | None = None) -> set[int]:
        """Contracts that other entries for this e-mail address already show."""
        return {
            int(cid)
            for entry in self._async_current_entries(include_ignore=False)
            if entry is not exclude
            and str(entry.data.get(CONF_EMAIL, "")).lower() == email.lower()
            for cid in entry.data.get(CONF_CONTRACT_IDS) or []
        }

    # --- reconfigure: change the selected contracts --------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if self._profile is None:
            try:
                self._profile = await self._api(entry.data.get(CONF_TOKEN)).profile()
            except KovnetAuthError:
                return self.async_abort(reason="reauth_required")
            except (KovnetError, aiohttp.ClientError, TimeoutError):
                _LOGGER.exception("Could not load KOVnet profile")
                return self.async_abort(reason="cannot_connect")

        selected = [int(cid) for cid in entry.data.get(CONF_CONTRACT_IDS) or []]
        other = self._configured_contracts(entry.data[CONF_EMAIL], exclude=entry)
        today = dt_util.now().date()
        contracts = {
            str(cid): c.label
            for cid, c in self._profile.contracts.items()
            if cid not in other and (cid in selected or c.is_current(today))
        }
        if not contracts:
            return self.async_abort(reason="no_contracts")

        if user_input is not None:
            chosen = [int(cid) for cid in user_input[CONF_CONTRACT_IDS]]
            if not chosen:
                errors["base"] = "no_contract_selected"
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_CONTRACT_IDS: chosen}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_contracts_schema(
                contracts, [cid for cid in map(str, selected) if cid in contracts]
            ),
            errors=errors,
        )

    # --- re-authentication ---------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._email = entry_data[CONF_EMAIL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            error = await self._login()
            if error == "need_code":
                return await self.async_step_code()
            if error is None:
                return await self._after_login()
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=PASSWORD_SCHEMA,
            errors=errors,
            description_placeholders={"email": self._email},
        )


def _contracts_schema(contracts: dict[str, str], default: list[str]) -> vol.Schema:
    return vol.Schema(
        {vol.Required(CONF_CONTRACT_IDS, default=default): cv.multi_select(contracts)}
    )
