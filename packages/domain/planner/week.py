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

from packages.contracts.api.applications import WEEKDAYS, PlannerSettings
from packages.domain.planner.rules import (
    effective_est_minutes,
    local_day_start_utc,
    local_today,
)


@dataclass
class InterviewSlot:
    """One scheduled round, already resolved to the company it belongs to."""

    application_id: str
    company: str
    at: datetime  # UTC
    round_type: Optional[str] = None
    duration_minutes: Optional[int] = None


@dataclass
class DueItem:
    """A pending to-do's due instant and what it costs.

    Carries the type alongside est_minutes because est_minutes is nullable and
    the per-type default is the only honest fill — see effective_est_minutes.
    The strip used to receive bare instants, which was enough to COUNT to-dos
    but not to total them.
    """

    at: datetime
    type: str
    est_minutes: Optional[int] = None


@dataclass
class ScheduledBlock:
    """A to-do the user placed at a time of day (V8's scheduled_at)."""

    action_id: str
    title: str
    at: datetime  # UTC
    type: str
    est_minutes: Optional[int] = None
    # Blocks survive completion on purpose (a finished block is still a true
    # record of how the day was spent), so the renderer needs to tell a done one
    # from an outstanding one — otherwise a cleared day draws identically to an
    # untouched one.
    status: str = "pending"


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


def contains(week_start: date, day: date) -> bool:
    return week_start <= day < week_start + timedelta(days=7)


def due_query_start_utc(week_start: date, today: date, tz: str) -> datetime:
    """Where per-day due counting should begin.

    When the week contains today, overdue work is attributed to today (that is
    where it is actually owed, and where the capacity bar counts it), so the
    per-day range starts at today — otherwise a to-do due earlier this week and
    still pending would appear both on the day it was due AND in today's carried
    count, showing two dots for one task.

    A week that does not contain today is a historical or forward view, where
    every day should simply report what fell due then, so counting starts at the
    week's own beginning."""
    return local_day_start_utc(today if contains(week_start, today) else week_start, tz)


def _local_date(dt: datetime, tz: str) -> date:
    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:  # SQLite round-trips drop tzinfo
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz)).date()


def build_week(
    *,
    interviews: list[InterviewSlot],
    due_items: list[DueItem],
    settings: PlannerSettings,
    now_utc: datetime,
    week_start: Optional[date] = None,
    carried_into_today: int = 0,
    carried_est_minutes: int = 0,
    blocks: Optional[list[ScheduledBlock]] = None,
) -> dict:
    """Seven days, Monday first. Anything outside the week is ignored rather
    than clamped into an edge day, which would overstate that day's load.

    Each day reports two different quantities and they must not be confused.
    `due_est_minutes` is what is OWED that day; `scheduled_est_minutes` is what
    has been given a time slot on it (V8). A to-do due Friday but scheduled for
    Wednesday contributes to Friday's owed total and Wednesday's scheduled one —
    that is the point of having both, and averaging them into one number would
    describe neither.

    `carried_into_today` is work that weighs on today without being due today:
    overdue and undated to-dos. It is added to today's count so the strip agrees
    with the capacity bar beneath it, which counts the same work. That makes
    today's number "what today owes" while other days read "what falls due
    then" — asymmetric, but honest: today is the only day that inherits a
    backlog. When the requested week doesn't contain today it is ignored, since
    there is no day for it to land on. `carried_est_minutes` is the same work
    measured in minutes and is folded into today the same way: a strip whose
    count included the backlog but whose minutes did not would put two
    contradictory readings of today on one row."""
    tz = settings.timezone
    today = local_today(now_utc, tz)
    start = week_start or week_start_for(today)
    days = [start + timedelta(days=i) for i in range(7)]
    in_week = set(days)

    rest = {d for d in settings.rest_days if d in WEEKDAYS}

    by_day: dict[date, list[InterviewSlot]] = {d: [] for d in days}
    for slot in interviews:
        d = _local_date(slot.at, tz)
        if d in in_week:
            by_day[d].append(slot)
    for slots in by_day.values():
        slots.sort(key=lambda s: s.at)

    counts: dict[date, int] = {d: 0 for d in days}
    due_est: dict[date, int] = {d: 0 for d in days}
    for item in due_items:
        d = _local_date(item.at, tz)
        if d in in_week:
            counts[d] += 1
            # effective_est_minutes, never a raw column sum: est_minutes is
            # nullable by design, and treating NULL as zero would file a
            # 90-minute day as a 60-minute one.
            due_est[d] += effective_est_minutes(item.type, item.est_minutes)
    if today in in_week:
        counts[today] += carried_into_today
        due_est[today] += carried_est_minutes

    blocks_by_day: dict[date, list[ScheduledBlock]] = {d: [] for d in days}
    sched_est: dict[date, int] = {d: 0 for d in days}
    for b in blocks or []:
        d = _local_date(b.at, tz)
        if d in in_week:
            blocks_by_day[d].append(b)
            sched_est[d] += effective_est_minutes(b.type, b.est_minutes)
    for placed in blocks_by_day.values():
        placed.sort(key=lambda b: (b.at, b.action_id))

    return {
        "week_start": start.isoformat(),
        "days": [
            {
                "date": d.isoformat(),
                "due_count": counts[d],
                "due_est_minutes": due_est[d],
                "scheduled_est_minutes": sched_est[d],
                "interviews": [
                    {
                        "application_id": s.application_id,
                        "company": s.company,
                        "round_type": s.round_type,
                        "at": s.at,
                        "duration_minutes": s.duration_minutes,
                    }
                    for s in by_day[d]
                ],
                "blocks": [
                    {
                        "action_id": b.action_id,
                        "title": b.title,
                        "at": b.at,
                        # Resolved here, so the strip never needs its own copy
                        # of the per-type default table.
                        "est_minutes": effective_est_minutes(b.type, b.est_minutes),
                        "status": b.status,
                    }
                    for b in blocks_by_day[d]
                ],
                "is_rest": WEEKDAYS[d.weekday()] in rest,
                "is_today": d == today,
            }
            for d in days
        ],
    }
