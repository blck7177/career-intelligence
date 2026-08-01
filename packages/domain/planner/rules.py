"""Planner daily rules engine — PURE functions, no DB, no clock of its own.

`generate_actions()` takes a snapshot (applications + their events/actions, the
existing global actions, settings, and `now_utc`) and returns a list of
`ActionSpec`s the worker should create. It is idempotent by construction: it
never emits a spec that a matching pending/dismissed auto-action already
suppresses, so re-running the daily beat produces no duplicates.

Day-boundary contract (matches PlannerSettings docstring): "today" is the
calendar day in `settings.timezone`; every due_at is the UTC instant of that
local day's 00:00, so the Today query's `due_at <= now(utc)` needs no change —
an action becomes due from local midnight of its due date.

Rules (thresholds all read from settings):
  1. follow_up   — applied ≥ follow_up_days ago, no employer response since, no
                   completed follow-up yet.
  2. thank_you   — a just-occurred interview (within 24h) → note due the next
                   WORKING day (this one is perishable, see rest days below).
  3. check_in    — an interview ≥ interview_checkin_days ago with nothing since.
  4. apply_or_drop — a plan-to-apply sitting ≥ apply_or_drop_days.
  5. queue_refill  — planned count < weekly apply target → one global "run
                   discovery" to-do (deduped per ISO week).
(3B7/networking is intentionally NOT here — deferred, see exec_plan W2-C1.)

Rest days (settings.rest_days) gate rules 1, 3, 4 and 5 — the ones whose trigger
PERSISTS, so skipping a day defers them. Rule 2 is exempt because its trigger is
a 24h window: skipping it would destroy the reminder rather than defer it, so it
still fires and lands on the next working day. Either way nothing NEW comes due
on the day off, and nothing already due is hidden — see is_rest_day().

Payload contract: every spec carries `rule` plus the facts that rule fired on,
so the UI can say *why* a to-do exists ("applied 9 days ago, no reply, 1st
follow-up") instead of showing an unexplained instruction. These fields are
whitelisted through ActionRead (see contracts), so keep them plain scalars and
free of anything the user should not see:
  follow_up     — days_since_applied
  thank_you     — interview_at (ISO 8601)
  check_in      — days_since_interview
  apply_or_drop — days_planned
  queue_refill  — planned_count, target
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from packages.contracts.api.applications import WEEKDAYS, PlannerSettings

# Events that count as the EMPLOYER responding (i.e. reasons NOT to nag a
# follow-up). User's own activity — notes, status changes, completed actions —
# deliberately does NOT suppress follow_up. "reply_received" joins this set once
# Gmail ingest (P2) exists.
EMPLOYER_RESPONSE_EVENTS = frozenset({"interview_scheduled"})

# An open/rejected auto-action of the same (application, type) suppresses
# regeneration. dismissed MUST be here — dismiss() writes no event and the rule
# predicates are state-based, so without it the beat resurrects a dismissed
# action every day.
_SUPPRESSING_STATUSES = frozenset({"pending", "dismissed"})

# Status written when an application closes and its outstanding to-dos are
# retired (JobApplicationRepository._cancel_pending_actions). It is defined here,
# next to the set it must stay out of, because that is the whole point of it
# being a separate word: retiring them as "dismissed" would make force-reopening
# a mis-closed application permanently silent for every rule that had a row.
RETIRED_STATUS = "cancelled"

# Effort estimate per action type, in minutes. Coarse on purpose — the point is
# a believable day total to check against the daily cap, not precision (an exact
# estimate would only lend false confidence to the planning fallacy). Keyed by
# the emitted ActionSpec.type, so check_in appears as "prep" and queue_refill as
# "global". The frontend keeps its own copy as the fallback for rows that
# predate this column.
DEFAULT_EST_MINUTES = {
    "follow_up": 15,
    "thank_you": 15,
    "prep": 30,
    "apply": 60,
    "global": 15,
    # Never emitted by a rule — these two only ever arrive from the user's own
    # quick-add, where est_minutes is optional. They are here because
    # effective_est_minutes() has to answer for EVERY action type: a day log
    # that silently counts an unestimated to-do as zero would report a lighter
    # day than the one the user was shown and agreed to.
    "networking": 20,
    "custom": 20,
}


def effective_est_minutes(type_: str, est_minutes: Optional[int]) -> int:
    """What this to-do costs, for any arithmetic that has to total a day.

    est_minutes is nullable — it arrived in V1 and was deliberately not
    backfilled, and quick-add leaves it unset unless you type a duration. The
    Today view has always filled the gap with a per-type default when it renders
    the capacity bar, so the server has to fill it the SAME way: the committed
    total stored in a day log is a snapshot of the number the user looked at
    before agreeing to it. Summing raw columns and treating NULL as zero would
    file a 90-minute morning as a 60-minute one.

    The frontend keeps its own copy of this table (EST_FALLBACK in
    PlanToday.tsx) because it must render before any of this runs; the two are
    asserted to agree in tests/tracker/test_planner_day.py."""
    if est_minutes is not None:
        return est_minutes
    return DEFAULT_EST_MINUTES.get(type_, 20)


# --- input / output views (the worker maps ORM rows into these) --------------


@dataclass
class EventView:
    event_type: str
    created_at: datetime  # UTC (when logged)
    at: Optional[datetime] = None  # UTC (when it happens, e.g. interview time); defaults to created_at
    round_type: Optional[str] = None  # interview round (recruiter_screen|phone|onsite|final); funnel onsite derivation


@dataclass
class ActionView:
    type: str
    status: str  # pending | done | dismissed | cancelled (see _SUPPRESSING_STATUSES)
    auto_generated: bool = True
    completed_at: Optional[datetime] = None  # UTC
    created_at: Optional[datetime] = None  # UTC (for global per-week dedup)
    payload: Optional[dict] = None


@dataclass
class ApplicationView:
    id: str
    status: str
    applied_at: Optional[datetime]  # UTC
    created_at: datetime  # UTC
    events: list[EventView] = field(default_factory=list)
    actions: list[ActionView] = field(default_factory=list)  # this app's actions, ANY status
    lane: Optional[str] = None  # a | b | c (effort tier); used by the weekly review
    channel: Optional[str] = None  # cold_apply|referral|... ; used by the weekly review


@dataclass(frozen=True)
class ActionSpec:
    type: str
    title: str
    application_id: Optional[str] = None
    due_at: Optional[datetime] = None  # UTC (local-midnight of the due date)
    payload: Optional[dict] = None
    est_minutes: Optional[int] = None  # effort estimate; per-type default below


# --- day-boundary helpers (the whole system's one definition of "today") -----


def local_today(now_utc: datetime, tz: str) -> date:
    return now_utc.astimezone(ZoneInfo(tz)).date()


def local_day_start_utc(d: date, tz: str) -> datetime:
    """The UTC instant of `d` 00:00 in `tz` — the canonical due_at encoding."""
    return datetime(d.year, d.month, d.day, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def is_rest_day(settings: PlannerSettings, now_utc: datetime) -> bool:
    """True when the workspace's local today is one of `settings.rest_days`.

    A rest day suppresses GENERATION only: no new auto-actions come due, so the
    day takes on no new debt. To-dos that came due earlier still appear in Today,
    because a day off is a decision not to add more — not a decision to pretend
    nothing is owed. Hiding them would also make the count jump back up on Monday
    with no explanation.

    It is not a decision to LOSE anything either — see next_working_day and the
    thank_you exemption in generate_actions.

    The weekday is resolved in settings.timezone, the same day boundary the rest
    of the planner uses, so "Saturday" starts at the user's local midnight and
    not UTC's."""
    return WEEKDAYS[local_today(now_utc, settings.timezone).weekday()] in settings.rest_days


def next_working_day(settings: PlannerSettings, d: date) -> date:
    """The first day on or after `d` that is not a rest day.

    Used to date work the engine must not drop onto a day off. Bounded at 8 tries
    and falling back to `d`: rest_days can legitimately contain all seven days,
    and a "find the next workday" loop over that configuration would never
    terminate. Falling back means the to-do lands on the rest day rather than
    vanishing — with every day marked off there is no better answer, and a
    visible to-do beats a silently deleted one."""
    for offset in range(8):
        cand = d + timedelta(days=offset)
        if WEEKDAYS[cand.weekday()] not in settings.rest_days:
            return cand
    return d


def _local_date(dt: datetime, tz: str) -> date:
    # Treat naive datetimes as UTC (SQLite round-trips can drop tzinfo).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz)).date()


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _suppressed(actions: list[ActionView], type_: str) -> bool:
    """True if an auto-action of this type is already pending or dismissed."""
    return any(
        a.auto_generated and a.type == type_ and a.status in _SUPPRESSING_STATUSES
        for a in actions
    )


# --- the engine --------------------------------------------------------------


def generate_actions(
    *,
    applications: list[ApplicationView],
    settings: PlannerSettings,
    now_utc: datetime,
    global_actions: Optional[list[ActionView]] = None,
) -> list[ActionSpec]:
    # This guard lives in the engine, not only in the beat, because rest_days is a
    # generation threshold like every other setting: any caller asking "what
    # should exist today" has to get the same answer.
    resting = is_rest_day(settings, now_utc)

    tz = settings.timezone
    today = local_today(now_utc, tz)
    due_today = local_day_start_utc(today, tz)
    specs: list[ActionSpec] = []

    for app in applications:
        # thank_you runs even on a rest day. Every other rule's trigger PERSISTS
        # ("applied ≥ 7 days ago" is still true on Monday), so skipping the beat
        # defers them. thank_you's trigger is a 24h window around the interview,
        # so skipping it DESTROYS the reminder: with the default sat+sun rest
        # days, a Friday-afternoon interview produced no thank-you to-do at all —
        # silently, and for the most time-critical prompt the planner has. Its
        # due date lands on the next working day, so the rest day still gains no
        # work.
        specs.extend(_thank_you(app, settings, now_utc, tz))
        if resting:
            continue
        specs.extend(_follow_up(app, settings, today, due_today, tz))
        specs.extend(_check_in(app, settings, today, due_today, tz))
        specs.extend(_apply_or_drop(app, settings, today, due_today, tz))

    if not resting:
        specs.extend(_queue_refill(applications, settings, now_utc, today, due_today, tz, global_actions or []))
    return specs


def _follow_up(app, settings, today, due_today, tz) -> list[ActionSpec]:
    if app.status != "applied" or app.applied_at is None:
        return []
    applied_date = _local_date(app.applied_at, tz)
    if (today - applied_date).days < settings.follow_up_days:
        return []
    applied_utc = _as_utc(app.applied_at)
    # Employer responded since we applied → no nag.
    if any(
        e.event_type in EMPLOYER_RESPONSE_EVENTS and _as_utc(e.created_at) >= applied_utc
        for e in app.events
    ):
        return []
    # Already followed up (completed) → one lifetime auto follow_up per app.
    if any(a.type == "follow_up" and a.completed_at is not None for a in app.actions):
        return []
    if _suppressed(app.actions, "follow_up"):
        return []
    # No "nth follow-up" counter here: the completed-check above makes this a
    # once-per-application rule, so any such counter would be a constant 1.
    return [
        ActionSpec(
            type="follow_up",
            title="Follow up on this application",
            application_id=app.id,
            due_at=due_today,
            payload={
                "rule": "follow_up",
                "days_since_applied": (today - applied_date).days,
            },
            est_minutes=DEFAULT_EST_MINUTES["follow_up"],
        )
    ]


def _thank_you(app, settings, now_utc, tz) -> list[ActionSpec]:
    if _suppressed(app.actions, "thank_you"):
        return []
    # A thank-you is owed the day after an interview that just happened (≤24h).
    recent = [
        e for e in app.events
        if e.event_type == "interview_scheduled"
        and timedelta(0) <= (now_utc - _as_utc(e.at or e.created_at)) <= timedelta(hours=24)
    ]
    if not recent:
        return []
    interview_at = _as_utc(max(e.at or e.created_at for e in recent))
    # The day after the interview, moved off a rest day if it lands on one. This
    # is the only rule that dates a FUTURE day, so it is the only one that can
    # schedule work onto a day the user marked off.
    due_date = next_working_day(settings, _local_date(interview_at, tz) + timedelta(days=1))
    due = local_day_start_utc(due_date, tz)
    return [
        ActionSpec(
            type="thank_you",
            title="Send a thank-you note",
            application_id=app.id,
            due_at=due,
            payload={
                "rule": "thank_you",
                "interview_at": interview_at.isoformat(),
            },
            est_minutes=DEFAULT_EST_MINUTES["thank_you"],
        )
    ]


def _check_in(app, settings, today, due_today, tz) -> list[ActionSpec]:
    if _suppressed(app.actions, "prep"):
        return []
    interviews = [e for e in app.events if e.event_type == "interview_scheduled"]
    if not interviews:
        return []
    last = max(interviews, key=lambda e: _as_utc(e.at or e.created_at))
    last_at = _as_utc(last.at or last.created_at)
    if (today - _local_date(last_at, tz)).days < settings.interview_checkin_days:
        return []
    # Nothing has happened since that interview (no later event).
    if any(_as_utc(e.created_at) > _as_utc(last.created_at) for e in app.events):
        return []
    return [
        ActionSpec(
            type="prep",
            title="Check in — no word since the interview",
            application_id=app.id,
            due_at=due_today,
            payload={
                "rule": "check_in",
                "days_since_interview": (today - _local_date(last_at, tz)).days,
            },
            est_minutes=DEFAULT_EST_MINUTES["prep"],
        )
    ]


def _apply_or_drop(app, settings, today, due_today, tz) -> list[ActionSpec]:
    if app.status != "planned":
        return []
    if (today - _local_date(app.created_at, tz)).days < settings.apply_or_drop_days:
        return []
    if _suppressed(app.actions, "apply"):
        return []
    return [
        ActionSpec(
            type="apply",
            title="Apply now or drop this one",
            application_id=app.id,
            due_at=due_today,
            payload={
                "rule": "apply_or_drop",
                "days_planned": (today - _local_date(app.created_at, tz)).days,
            },
            est_minutes=DEFAULT_EST_MINUTES["apply"],
        )
    ]


def _queue_refill(applications, settings, now_utc, today, due_today, tz, global_actions) -> list[ActionSpec]:
    planned = sum(1 for a in applications if a.status == "planned")
    if planned >= settings.weekly_target.apply:
        return []
    # Dedup per ISO week: skip if a queue_refill global to-do already exists
    # (pending or dismissed) created in the current local week.
    this_week = today.isocalendar()[:2]  # (year, week)
    for a in global_actions:
        if (a.payload or {}).get("rule") != "queue_refill":
            continue
        # A pending refill to-do blocks unconditionally — never open two. A
        # dismissed one only suppresses within its week (re-prompt next week);
        # created_at None (just-created / not-yet-populated) counts as this week.
        if a.status == "pending":
            return []
        if a.status == "dismissed" and (
            a.created_at is None or _local_date(a.created_at, tz).isocalendar()[:2] == this_week
        ):
            return []
    return [
        ActionSpec(
            type="global",
            title="Run a discovery to refill your apply queue",
            application_id=None,
            due_at=due_today,
            payload={
                "rule": "queue_refill",
                "planned_count": planned,
                "target": settings.weekly_target.apply,
            },
            est_minutes=DEFAULT_EST_MINUTES["global"],
        )
    ]
