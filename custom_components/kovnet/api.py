"""KOVnet client for the JSON API used by the KOVnet Ouderapp.

Login:   GET  auth/get_tokens/?email=..&password=..          (no 2FA)
         POST auth/get_tokens/ {"email", "password", "code"}  (2FA code from e-mail)
         -> {"success": true, "body": {"users": [{"token": <JWT, ~1 year>, ...}]}}
         -> {"success": false, "code": 15}  when a 2FA code is required
Other calls send "Authorization: Bearer <token>"; an invalid/expired token
gives {"success": false, "code": 10} (with HTTP 200).
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, time, timedelta
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_URL = "https://app.kovnet.nl/api/v2/"
CODE_TOKEN_INVALID = 10
CODE_2FA_REQUIRED = 15
TIMEOUT = aiohttp.ClientTimeout(total=30)
# "24:00" (end of day); datetime.time cannot represent it, see end_of_day().
END_OF_DAY = time.max


class KovnetError(Exception):
    """Generic KOVnet error."""


class KovnetAuthError(KovnetError):
    """Login failed or token invalid/expired."""


class KovnetTwoFactorRequired(KovnetAuthError):
    """KOVnet sent a verification code by e-mail; log in again with that code."""


class KovnetInvalidCode(KovnetAuthError):
    """The 2FA code was not accepted."""


@dataclass
class CareBlock:
    """One planned block on a day."""

    group_id: int | None
    group: str | None
    start: time
    end: time
    cancelled: bool
    remarks: str
    pending: bool = False  # request not (yet) approved

    @property
    def requested(self) -> bool:
        """Pending request that is not cancelled."""
        return self.pending and not self.cancelled


@dataclass
class CareDay:
    """All planning for one calendar day."""

    day: date
    blocks: list[CareBlock] = field(default_factory=list)
    closed: bool = False

    @property
    def active_blocks(self) -> list[CareBlock]:
        return [b for b in self.blocks if not b.cancelled and not b.pending]

    @property
    def has_care(self) -> bool:
        return not self.closed and bool(self.active_blocks)

    @property
    def cancelled(self) -> bool:
        return any(b.cancelled for b in self.blocks) and not self.active_blocks

    @property
    def requested_blocks(self) -> list[CareBlock]:
        return [b for b in self.blocks if b.requested]

    @property
    def pending(self) -> bool:
        return bool(self.requested_blocks)

    @property
    def start(self) -> time | None:
        return min((b.start for b in self.active_blocks), default=None)

    @property
    def end(self) -> time | None:
        return max((b.end for b in self.active_blocks), default=None)

    @property
    def groups(self) -> list[str]:
        src = self.active_blocks or self.blocks
        return sorted({b.group for b in src if b.group})

    @property
    def remarks(self) -> str:
        return ", ".join(
            r for r in dict.fromkeys(b.remarks.strip(" ,") for b in self.blocks) if r
        )


@dataclass
class Schedule:
    """Schedule for one contract (one or more months merged)."""

    child_name: str | None
    days: dict[date, CareDay]


@dataclass
class KovnetUser:
    """One account (organisation) returned by the login call."""

    user_id: int | None
    token: str
    organization: str | None


@dataclass
class Contract:
    id: int
    child_name: str | None
    start: date | None
    end: date | None
    archive: bool

    def is_current(self, today: date) -> bool:
        return not self.archive and (self.end is None or self.end >= today)

    @property
    def label(self) -> str:
        period = " t/m ".join(d.strftime("%d-%m-%Y") for d in (self.start, self.end) if d)
        return f"{self.child_name or 'Kind'} ({period or self.id})"


@dataclass
class Profile:
    user_id: int | None
    contracts: dict[int, Contract]
    group_names: dict[int, str]


def _date(value: Any) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _hm(entry: dict, prefix: str) -> time:
    hours = int(entry.get(f"{prefix}_hours") or 0)
    minutes = int(entry.get(f"{prefix}_minutes") or 0)
    if hours >= 24:
        return END_OF_DAY
    return time(hours, minutes)


def parse_profile(body: dict) -> Profile:
    try:
        children = {c["id"]: c for c in body.get("children") or [] if "id" in c}
        groups = {
            g["id"]: g.get("name")
            for loc in body.get("locations") or []
            for g in loc.get("groups") or []
            if "id" in g
        }
        contracts: dict[int, Contract] = {}
        for c in body.get("contracts") or []:
            child = children.get(c.get("child_id")) or {}
            cid = int(c["id"])
            contracts[cid] = Contract(
                id=cid,
                child_name=child.get("firstname") or child.get("normal_name"),
                start=_date(c.get("start_date")),
                end=_date(c.get("end_date")),
                archive=bool(c.get("archive")),
            )
        user = body.get("user") or {}
        return Profile(user_id=user.get("id"), contracts=contracts, group_names=groups)
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise KovnetError(f"Onverwacht profielformaat: {err!r}") from err


def parse_schedule(
    body: dict, year: int, month: int, group_names: dict[int, str]
) -> dict[date, CareDay]:
    """Parse a contracts/<id>/schedule body into one CareDay per day of the month."""
    try:
        return _parse_schedule(body, year, month, group_names)
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise KovnetError(f"Onverwacht roosterformaat: {err!r}") from err


def _period(item: dict) -> tuple[date | None, date | None]:
    start = _date(item.get("start_date") or item.get("date"))
    return start, _date(item.get("end_date")) or start


def _parse_schedule(
    body: dict, year: int, month: int, group_names: dict[int, str]
) -> dict[date, CareDay]:
    first = date(year, month, 1)
    days = {
        first + timedelta(i): CareDay(day=first + timedelta(i))
        for i in range(calendar.monthrange(year, month)[1])
    }
    for workday in body.get("workdays") or []:
        day = _date(workday.get("date"))
        if day is None:
            continue
        care = days.setdefault(day, CareDay(day=day))
        for occ in workday.get("occupations") or []:
            care.blocks.append(
                CareBlock(
                    group_id=occ.get("group_id"),
                    group=group_names.get(occ.get("group_id")),
                    start=_hm(occ, "starttime"),
                    end=_hm(occ, "endtime"),
                    cancelled=bool(occ.get("cancelled")) or bool(occ.get("on_waiting_list")),
                    pending=occ.get("authorized") is False,
                    remarks=occ.get("remarks") or "",
                )
            )

    meta = body.get("meta") or {}
    # Explicit closings (holidays, study days); may be limited to one group.
    for closing in meta.get("closings") or []:
        start, end = _period(closing)
        if start is None:
            continue
        gid = closing.get("group_id")
        for day, care in days.items():
            if start <= day <= end and (
                gid is None or not care.blocks or any(b.group_id == gid for b in care.blocks)
            ):
                care.closed = True
    # Closed weeks: only mark weekdays without any planning, never override a block.
    for week in meta.get("closed_weeks") or []:
        start, end = _period(week)
        if start is None:
            continue
        for day, care in days.items():
            if start <= day <= end and day.weekday() < 5 and not care.blocks:
                care.closed = True
    return days


class KovnetApi:
    """Thin async wrapper around the KOVnet app API."""

    def __init__(self, session: aiohttp.ClientSession, token: str | None = None) -> None:
        self._session = session
        self.token = token

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        auth: bool = True,
    ) -> dict:
        headers = {"Accept": "application/json"}
        if auth:
            if not self.token:
                raise KovnetAuthError("Geen token; opnieuw inloggen nodig")
            headers["Authorization"] = f"Bearer {self.token}"
        async with self._session.request(
            method, API_URL + path, params=params, json=json, headers=headers, timeout=TIMEOUT
        ) as resp:
            if resp.status in (401, 403):
                raise KovnetAuthError(f"Geen toegang (HTTP {resp.status})")
            # Not raise_for_status(): its message contains the full URL, and for
            # the login call that includes the password (query parameters).
            if resp.status >= 400:
                raise KovnetError(f"KOVnet gaf HTTP {resp.status} bij {path}")
            try:
                data = await resp.json(content_type=None)
            except ValueError as err:
                raise KovnetError("KOVnet gaf geen geldige JSON terug") from err
        if not isinstance(data, dict):
            raise KovnetError("Onverwacht antwoord van KOVnet")
        return data

    async def _get_body(self, path: str, params: dict | None = None) -> dict:
        data = await self._call("GET", path, params=params)
        if not data.get("success"):
            code = data.get("code")
            if code == CODE_TOKEN_INVALID:
                raise KovnetAuthError("Token ongeldig of verlopen")
            raise KovnetError(f"KOVnet-fout bij {path} (code {code})")
        return data.get("body") or {}

    async def login(self, email: str, password: str, code: str | None = None) -> list[KovnetUser]:
        """Log in; returns the parent accounts. Does NOT change self.token."""
        if code is None:
            # Same as the app: credentials as query parameters (over HTTPS).
            data = await self._call(
                "GET", "auth/get_tokens/", params={"email": email, "password": password}, auth=False
            )
        else:
            data = await self._call(
                "POST",
                "auth/get_tokens/",
                json={"email": email, "password": password, "code": code},
                auth=False,
            )
        if not data.get("success"):
            err_code = data.get("code")
            if err_code == CODE_2FA_REQUIRED and code is None:
                raise KovnetTwoFactorRequired("KOVnet heeft een verificatiecode gemaild")
            if code is not None:
                raise KovnetInvalidCode(f"Code niet geaccepteerd (code {err_code})")
            raise KovnetAuthError(f"Inloggen mislukt (code {err_code})")
        users = [
            KovnetUser(
                user_id=u.get("user_id"),
                token=u["token"],
                organization=(u.get("organization") or {}).get("name"),
            )
            for u in (data.get("body") or {}).get("users") or []
            if u.get("parent_user") and u.get("token")
        ]
        if not users:
            raise KovnetAuthError("Geen ouderaccount gevonden bij dit e-mailadres")
        return users

    async def profile(self) -> Profile:
        return parse_profile(await self._get_body("user/profile/"))

    async def schedule(
        self, contract_id: int, year: int, month: int, group_names: dict[int, str]
    ) -> dict[date, CareDay]:
        body = await self._get_body(
            f"contracts/{contract_id}/schedule", {"month": str(month), "year": str(year)}
        )
        return parse_schedule(body, year, month, group_names)
