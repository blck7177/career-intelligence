"""Planner week strip — PURE bucketing of a week's commitments by local day.

The Today view needs the week's shape at a glance: which days already carry a
hard commitment (an interview), how much is due on each, and which are rest
days. Interviews are the skeleton of a day — you plan around them, not over
them — so they have to be visible before the day is planned, not discovered
inside an application's timeline.

Same day-boundary contract as the rules engine: a day is a calendar day in
settings.timezone, so an interview at 23:30 UTC Sunday belongs to Sunday or
Monday depending on the zone, and the strip must agree with what the Today
query considers "today".

No DB and no clock of its own — the caller passes the week's commitments and
now_utc.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from packages.contracts.api.applications import PlannerSettings
from packages.domain.planner.rules import local_day_start_utc, local_today

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class InterviewSlot:
    """One scheduled round, already resolved to the company it belongs to."""

    application_id: str
    company: str
    at: datetime  # UTC
    round_type: Optional[str] = None


def week_start_for(ref: date) -> date:
    """The Monday of ref's week. Weeks are Mon..Sun everywhere in the planner."""
    return ref - timedelta(days=ref.weekday())


def week_bounds_utc(week_start: date, tz: str) -> tuple[datetime, datetime]:
    """[start, end) in UTC for a local Mon..Sun week — the range a caller should
    query on, so it never has to reason about the zone itself."""
    return (
        local_day_start_utc(week_start, tz),
        local_day_start_utc(week_start + timedelta(days=7), tz),
    )


def _local_date(dt: datetime, tz: str) -> date:
    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:  # SQLite round-trips drop tzinfo
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz)).date()


def build_week(
    *,
    interviews: list[InterviewSlot],
    due_ats: list[datetime],
    settings: PlannerSettings,
    now_utc: datetime,
    week_start: Optional[date] = None,
) -> dict:
    """Seven days, Monday first. `due_ats` are the due instants of pending
    to-dos; only their count per day matters here — the Today list is where the
    to-dos themselves live. Anything outside the week is ignored rather than
    clamped into an edge day, which would overstate that day's load."""
    tz = settings.timezone
    today = local_today(now_utc, tz)
    start = week_start or week_start_for(today)
    days = [start + timedelta(days=i) for i in range(7)]
    in_week = set(days)

    rest = {d for d in settings.rest_days if d in _WEEKDAY_KEYS}

    by_day: dict[date, list[InterviewSlot]] = {d: [] for d in days}
    for slot in interviews:
        d = _local_date(slot.at, tz)
        if d in in_week:
            by_day[d].append(slot)
    for slots in by_day.values():
        slots.sort(key=lambda s: s.at)

    counts: dict[date, int] = {d: 0 for d in days}
    for due in due_ats:
        d = _local_date(due, tz)
        if d in in_week:
            counts[d] += 1

    return {
        "week_start": start.isoformat(),
        "days": [
            {
                "date": d.isoformat(),
                "due_count": counts[d],
                "interviews": [
                    {
                        "application_id": s.application_id,
                        "company": s.company,
                        "round_type": s.round_type,
                        "at": s.at,
                    }
                    for s in by_day[d]
                ],
                "is_rest": _WEEKDAY_KEYS[d.weekday()] in rest,
                "is_today": d == today,
            }
            for d in days
        ],
    }
