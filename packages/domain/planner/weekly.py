"""Planner weekly review — PURE aggregation over the same ApplicationView
snapshot the rules engine and funnel use, plus the LLM prompt builder.

`build_weekly_stats()` turns a workspace's applications into a `WeeklyReviewStats`
(the deterministic numbers stored in planner_reviews.stats_json and narrated by
the LLM). No DB, no clock of its own — the caller passes the reviewed week's
Monday (a local date in settings.timezone) and now_utc.

`weekly_review_prompt()` builds the (system, user) messages for the narrative.
The narrative is a nicety; on any LLM failure the service persists stats with a
NULL narrative and the card degrades to the number-only template.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from typing import Optional

from packages.contracts.api.applications import (
    FunnelStage,
    PlannerSettings,
    WeeklyReviewStats,
)
from packages.domain.planner.funnel import build_funnel
from packages.domain.planner.rules import (
    ActionView,
    ApplicationView,
    local_day_start_utc,
)

# Statuses that mean the application was actually submitted at some point (used
# for the honest application→interview conversion denominator).
_APPLIED_OR_FURTHER = frozenset(
    {"applied", "in_review", "interviewing", "offer", "rejected", "ghosted"}
)
_LANE_KEYS = ("a", "b", "c")


def _count_done_in_window(actions: list[ActionView], type_: str, start, end) -> int:
    return sum(
        1
        for a in actions
        if a.type == type_
        and a.status == "done"
        and a.completed_at is not None
        and start <= _as_aware(a.completed_at) < end
    )


def _as_aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _reached_interview(app: ApplicationView) -> bool:
    return app.status in ("interviewing", "offer") or any(
        e.event_type == "interview_scheduled" for e in app.events
    )


def build_weekly_stats(
    applications: list[ApplicationView],
    settings: PlannerSettings,
    week_start: date,
    now_utc: datetime,
    *,
    global_actions: Optional[list[ActionView]] = None,
) -> WeeklyReviewStats:
    """Aggregate one workspace's applications into the weekly review numbers.
    `week_start` is the reviewed week's Monday in settings.timezone.

    `global_actions` are the workspace's application_id-NULL actions (standalone
    to-dos). They MUST be passed so the outreach/follow_ups triplet matches
    PlannerStats, whose SQL count has no application_id filter — otherwise a
    completed standalone networking/follow-up to-do shows up on the Today card
    but is invisible in the weekly review."""
    tz = settings.timezone
    start = local_day_start_utc(week_start, tz)
    end = local_day_start_utc(week_start + timedelta(days=7), tz)
    globals_ = global_actions or []

    # This-week cadence triplet (SAME definitions as PlannerStats — per-application
    # AND standalone/global actions, matching count_completed_by_type_in_range,
    # which filters only workspace/type/status/completed_at):
    #   applied    = applications whose applied_at fell in the week,
    #   outreach   = networking actions completed in the week,
    #   follow_ups = follow_up actions completed in the week.
    applied = sum(
        1
        for a in applications
        if a.applied_at is not None and start <= _as_aware(a.applied_at) < end
    )
    outreach = (
        sum(_count_done_in_window(a.actions, "networking", start, end) for a in applications)
        + _count_done_in_window(globals_, "networking", start, end)
    )
    follow_ups = (
        sum(_count_done_in_window(a.actions, "follow_up", start, end) for a in applications)
        + _count_done_in_window(globals_, "follow_up", start, end)
    )

    # Current pipeline snapshot — reuse the funnel's single stage definition
    # (planned → applied → in_review → interviewing → onsite → offer).
    funnel_result = build_funnel(applications, settings, now_utc)
    funnel = [FunnelStage(**s) for s in funnel_result["stages"]]

    by_lane: dict[str, int] = {k: 0 for k in _LANE_KEYS}
    by_lane["none"] = 0
    by_channel: dict[str, int] = {}
    for a in applications:
        key = a.lane if a.lane in _LANE_KEYS else "none"
        by_lane[key] += 1
        channel = a.channel or "unknown"
        by_channel[channel] = by_channel.get(channel, 0) + 1

    applied_total = sum(1 for a in applications if a.status in _APPLIED_OR_FURTHER)
    reached_interview = sum(
        1 for a in applications if a.status in _APPLIED_OR_FURTHER and _reached_interview(a)
    )
    interview_rate = (reached_interview / applied_total) if applied_total else 0.0

    return WeeklyReviewStats(
        week_start=week_start.isoformat(),
        applied=applied,
        outreach=outreach,
        follow_ups=follow_ups,
        weekly_target=settings.weekly_target,
        funnel=funnel,
        by_lane=by_lane,
        by_channel=by_channel,
        applied_total=applied_total,
        reached_interview=reached_interview,
        interview_rate=round(interview_rate, 3),
    )


_SYSTEM_PROMPT = (
    "You are a concise, encouraging job-search coach writing a short weekly "
    "review for one job seeker. You are given a JSON block of that person's "
    "own tracked numbers for the week. Write 3-5 sentences of plain prose (no "
    "markdown headers, no bullet lists, no invented facts): acknowledge the "
    "week's effort against the weekly targets, name one thing going well and "
    "one concrete thing to focus on next week, grounded ONLY in the numbers "
    "given. If applied is 0, be gentle, not alarmist. Never state or imply that "
    "an employer replied or ghosted — the tracker only knows what the user "
    "logged, not their inbox. Do not repeat every number back; interpret them."
)


def weekly_review_prompt(stats: WeeklyReviewStats) -> tuple[str, str]:
    """(system, user) messages for the narrative. The user message is the stats
    as a JSON data block — the model interprets, never parses further input."""
    payload = json.dumps(stats.model_dump(), ensure_ascii=False, indent=2)
    user = (
        "Here are this week's tracked job-search numbers. Write the review.\n\n"
        f"<weekly_stats>\n{payload}\n</weekly_stats>"
    )
    return _SYSTEM_PROMPT, user
