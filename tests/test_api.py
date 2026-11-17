"""Tests for the KOVnet API client (parsing, token, error handling)."""
from __future__ import annotations

import asyncio
import base64
from datetime import UTC, date, datetime, time
import json

import pytest

import kovnet_api as api

GROUPS = {1: "Kikkers", 2: "Vlinders"}


def occ(group_id=1, start=8, end=13, **extra):
    return {
        "group_id": group_id,
        "starttime_hours": start,
        "starttime_minutes": 0,
        "endtime_hours": end,
        "endtime_minutes": 0,
        **extra,
    }


def schedule(workdays=(), **meta):
    body = {"workdays": [{"date": d, "occupations": o} for d, o in workdays], "meta": meta}
    return api.parse_schedule(body, 2026, 11, GROUPS)


def test_every_day_of_the_month():
    days = schedule()
    assert len(days) == 30
    assert all(not d.has_care for d in days.values())


def test_care_block():
    d = schedule([("2026-11-18", [occ(start=8, end=17, remarks="Neemt slaapzak mee")])])[
        date(2026, 11, 18)
    ]
    assert d.has_care
    assert (d.start, d.end) == (time(8), time(17))
    assert d.groups == ["Kikkers"]
    assert d.remarks == "Neemt slaapzak mee"


def test_multiple_blocks_span_the_day():
    d = schedule([("2026-11-18", [occ(1, 8, 12), occ(2, 13, 18)])])[date(2026, 11, 18)]
    assert (d.start, d.end) == (time(8), time(18))
    assert d.groups == ["Kikkers", "Vlinders"]


def test_end_of_day():
    d = schedule([("2026-11-18", [occ(end=24)])])[date(2026, 11, 18)]
    assert d.end == api.END_OF_DAY


def test_cancelled_and_waiting_list():
    days = schedule(
        [
            ("2026-11-18", [occ(cancelled=True)]),
            ("2026-11-19", [occ(on_waiting_list=True)]),
        ]
    )
    for day in (18, 19):
        d = days[date(2026, 11, day)]
        assert d.cancelled and not d.has_care and not d.pending


def test_pending_request():
    d = schedule([("2026-11-18", [occ(authorized=False)])])[date(2026, 11, 18)]
    assert d.pending and not d.has_care and not d.cancelled
    assert [b.group for b in d.requested_blocks] == ["Kikkers"]


def test_closing_for_all_groups():
    days = schedule(
        [("2026-11-18", [occ()])],
        closings=[{"start_date": "2026-11-18", "end_date": "2026-11-19"}],
    )
    assert days[date(2026, 11, 18)].closed and not days[date(2026, 11, 18)].has_care
    assert days[date(2026, 11, 19)].closed
    assert not days[date(2026, 11, 20)].closed


def test_closing_for_other_group_keeps_care():
    days = schedule(
        [("2026-11-18", [occ(group_id=1)])],
        closings=[{"date": "2026-11-18", "group_id": 2}],
    )
    assert days[date(2026, 11, 18)].has_care


def test_closed_week_only_marks_unplanned_weekdays():
    days = schedule(
        [("2026-11-17", [occ()])],
        closed_weeks=[{"start_date": "2026-11-16", "end_date": "2026-11-22"}],
    )
    assert days[date(2026, 11, 16)].closed
    assert not days[date(2026, 11, 17)].closed  # planned block wins
    assert not days[date(2026, 11, 21)].closed  # Saturday


def test_bad_schedule_raises_kovnet_error():
    with pytest.raises(api.KovnetError):
        api.parse_schedule({"workdays": [{"date": "geen datum"}]}, 2026, 11, GROUPS)


def test_profile():
    profile = api.parse_profile(
        {
            "user": {"id": 7},
            "children": [{"id": 3, "firstname": "Sam"}],
            "locations": [{"groups": [{"id": 1, "name": "Kikkers"}]}],
            "contracts": [
                {"id": 11, "child_id": 3, "start_date": "2025-01-01", "end_date": None},
                {"id": 12, "child_id": 3, "end_date": "2025-12-31"},
                {"id": 13, "child_id": 3, "archive": 1},
            ],
        }
    )
    assert profile.user_id == 7
    assert profile.group_names == {1: "Kikkers"}
    today = date(2026, 11, 17)
    assert [cid for cid, c in profile.contracts.items() if c.is_current(today)] == [11]
    assert profile.contracts[11].label == "Sam (01-01-2025)"


def _jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.handtekening"


def test_token_expiry():
    assert api.token_expiry(_jwt({"exp": 1800000000})) == datetime.fromtimestamp(
        1800000000, UTC
    )


@pytest.mark.parametrize("token", [None, "", "geen-jwt", "a.b.c", _jwt({"sub": 1})])
def test_token_expiry_unreadable(token):
    assert api.token_expiry(token) is None


class FakeResponse:
    def __init__(self, status: int, data=None) -> None:
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._data


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def test_http_error_does_not_leak_password():
    client = api.KovnetApi(FakeSession(FakeResponse(502)))
    with pytest.raises(api.KovnetError) as err:
        asyncio.run(client.login("ouder@example.com", "geheim123"))
    assert "geheim123" not in str(err.value)
    assert "502" in str(err.value)


def test_login_requires_code():
    client = api.KovnetApi(FakeSession(FakeResponse(200, {"success": False, "code": 15})))
    with pytest.raises(api.KovnetTwoFactorRequired):
        asyncio.run(client.login("ouder@example.com", "geheim123"))


def test_login_returns_parent_accounts():
    body = {
        "success": True,
        "body": {
            "users": [
                {"user_id": 1, "token": "t1", "parent_user": True, "organization": {"name": "A"}},
                {"user_id": 2, "token": "t2", "parent_user": False},
            ]
        },
    }
    session = FakeSession(FakeResponse(200, body))
    users = asyncio.run(api.KovnetApi(session).login("ouder@example.com", "geheim123", "1234"))
    assert [(u.user_id, u.organization) for u in users] == [(1, "A")]
    method, _, kwargs = session.calls[0]
    assert method == "POST" and kwargs["json"]["code"] == "1234"


def test_invalid_token():
    client = api.KovnetApi(FakeSession(FakeResponse(200, {"success": False, "code": 10})), "t")
    with pytest.raises(api.KovnetAuthError):
        asyncio.run(client.profile())
