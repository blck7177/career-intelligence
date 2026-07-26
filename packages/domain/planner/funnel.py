"""Planner funnel + alerts — PURE functions over the same ApplicationView
snapshot the rules engine uses (status, applied_at, events incl. interview
rounds). Returns pipeline stage counts + advisory alerts. No DB, no own clock.

Stages: planned → applied → in_review → interviewing → onsite → offer, where
onsite is DERIVED (an active application with an interview_scheduled event whose
round_type == "onsite"), not a status.

Alerts (all advisory — the UI decides what to surface; ghosted_suggestion is the
audit-D confirm-gate: proposed here, applied only when the user clicks):
  - supply_drought: applies this week < weekly apply target AND late-stage > 0.
  - ghosted_suggestion (per app): applied ≥ ghost_days with no employer response.
  - check_in (per app): interviewing ≥ interview_checkin_days with nothing since.
  - onsite_low: live onsites < onsite_target.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from packages.contracts.api.applications import PlannerSettings
from packages.domain.planner.rules import (
    EMPLOYER_RESPONSE_EVENTS,
    ApplicationView,
    _as_utc,
    _local_date,
    local_today,
)

_CLOSED = frozenset({"rejected", "withdrawn", "ghosted"})
_STAGE_STATUSES = ("planned", "applied", "in_review", "interviewing", "offer")


@dataclass
class FunnelStage:
    key: str
    count: int


@dataclass
class Alert:
    kind: str
    severity: str  # info | warn
    application_id: Optional[str]
    message_key: str  # i18n key the frontend renders
    context: dict = field(default_factory=dict)


def _has_live_onsite(app: ApplicationView) -> bool:
    return app.status not in _CLOSED and any(
        e.event_type == "interview_scheduled" and e.round_type == "onsite" for e in app.events
    )


def _employer_event_since(app: ApplicationView, since_utc: datetime) -> bool:
    return any(
        e.event_type in EMPLOYER_RESPONSE_EVENTS and _as_utc(e.created_at) >= since_utc
        for e in app.events
    )


def build_funnel(
    applications: list[ApplicationView], settings: PlannerSettings, now_utc: datetime
) -> dict:
    tz = settings.timezone
    today = local_today(now_utc, tz)

    counts = {s: 0 for s in _STAGE_STATUSES}
    onsite = 0
    for a in applications:
        if a.status in counts:
            counts[a.status] += 1
        if _has_live_onsite(a):
            onsite += 1

    stages = [FunnelStage(k, counts[k]) for k in ("planned", "applied", "in_review", "interviewing")]
    stages.append(FunnelStage("onsite", onsite))
    stages.append(FunnelStage("offer", counts["offer"]))

    alerts: list[Alert] = []
    this_week = today.isocalendar()[:2]
    applies_this_week = sum(
        1
        for a in applications
        if a.applied_at is not None and _local_date(a.applied_at, tz).isocalendar()[:2] == this_week
    )
    late_stage = counts["interviewing"] + counts["offer"]
    if applies_this_week < settings.weekly_target.apply and late_stage > 0:
        alerts.append(
            Alert("supply_drought", "warn", None, "alert.supplyDrought",
                  {"applied": applies_this_week, "target": settings.weekly_target.apply})
        )

    for a in applications:
        if a.status == "applied" and a.applied_at is not None:
            days = (today - _local_date(a.applied_at, tz)).days
            if days >= settings.ghost_days and not _employer_event_since(a, _as_utc(a.applied_at)):
                alerts.append(
                    Alert("ghosted_suggestion", "warn", a.id, "alert.ghostedSuggestion", {"days": days})
                )
        elif a.status == "interviewing" and a.events:
            last = max(_as_utc(e.created_at) for e in a.events)
            days = (today - _local_date(last, tz)).days
            if days >= settings.interview_checkin_days:
                alerts.append(
                    Alert("check_in", "info", a.id, "alert.checkIn", {"days": days})
                )

    if onsite < settings.onsite_target:
        alerts.append(
            Alert("onsite_low", "info", None, "alert.onsiteLow",
                  {"onsite": onsite, "target": settings.onsite_target})
        )

    return {"stages": [asdict(s) for s in stages], "alerts": [asdict(a) for a in alerts]}
