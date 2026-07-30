"""Weekly review generation (Wave 5).

Orchestrates one workspace's weekly review: gather the application snapshot, run
the PURE aggregator (packages/domain/planner/weekly.py), narrate it with a cheap
LLM call, and upsert the planner_reviews row. The narrative is best-effort — any
LLMCallError degrades to a NULL narrative (the card renders the number-only
template). Zero-cost otherwise: one small chat completion per workspace per week.

`generate_weekly_review(session, workspace_id, now_utc, week_start=None)` is the
testable core; the weekly Celery beat wraps it with get_session() + the real
clock. When week_start is None it defaults to the Monday of the workspace's
current local week (settings.timezone) — i.e. the just-finished week when the
beat fires Sunday night.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from packages.domain.planner.rules import ApplicationView, local_today
from packages.domain.planner.settings import load_planner_settings
from packages.domain.planner.weekly import DayLogView, build_weekly_stats, weekly_review_prompt
from packages.infrastructure.db.models import PlannerReview
from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    ApplicationEventRepository,
    JobApplicationRepository,
    PlannerDayLogRepository,
    PlannerReviewRepository,
    WorkspaceRepository,
)
from packages.infrastructure.llm.client import get_llm_client
from packages.infrastructure.planner_mapping import action_view, application_view
from packages.infrastructure.llm.usage_writer import set_llm_context

logger = logging.getLogger(__name__)

# Narrative is short prose; keep the completion budget small (cost + latency).
_NARRATIVE_MAX_TOKENS = 400


def _week_start_for(now_utc: datetime, tz: str) -> date:
    """Monday of the most-recent COMPLETE Mon..Sun week in `tz`.

    The weekly beat fires ~Monday 02:00 UTC, so local "today" is Sunday
    (Americas, offset ≤ -3h) or Monday (everywhere else). Anchoring on
    (today − 1 day) lands in the just-finished week for EVERY zone — without the
    −1 day, non-Americas workspaces would review the brand-new (≈empty) week."""
    today = local_today(now_utc, tz)
    anchor = today - timedelta(days=1)
    return anchor - timedelta(days=anchor.weekday())


def _gather_views(session: Any, workspace_id: str) -> list[ApplicationView]:
    app_repo = JobApplicationRepository(session)
    event_repo = ApplicationEventRepository(session)
    action_repo = ApplicationActionRepository(session)
    return [
        application_view(
            app,
            event_repo.list_for_application(app.id, workspace_id),
            action_repo.list_for_application(app.id, workspace_id),
        )
        for app in app_repo.list_for_workspace(workspace_id, limit=10_000)
    ]


def generate_weekly_review(
    session: Any,
    workspace_id: str,
    *,
    now_utc: datetime,
    week_start: Optional[date] = None,
) -> Optional[PlannerReview]:
    """Build + persist one workspace's weekly review. Returns the row, or None if
    the workspace no longer exists. Never raises on LLM failure — degrades to a
    NULL narrative."""
    workspace = WorkspaceRepository(session).get(workspace_id)
    if workspace is None:
        return None
    settings = load_planner_settings(workspace)
    if week_start is None:
        week_start = _week_start_for(now_utc, settings.timezone)

    views = _gather_views(session, workspace_id)
    # Standalone (application_id-NULL) actions count toward the outreach/follow_up
    # triplet too, so the review's numbers match /planner-stats.
    global_actions = [
        action_view(a)
        for a in ApplicationActionRepository(session).list_global_for_workspace(workspace_id)
    ]
    # This week's ritual records, for the plan-versus-actual strip. Absent days
    # stay absent (see build_weekly_stats).
    day_logs = [
        DayLogView(
            local_date=row.local_date,
            committed_est=row.committed_est,
            done_est=row.done_est,
        )
        for row in PlannerDayLogRepository(session).list_for_range(
            workspace_id, week_start, week_start + timedelta(days=7)
        )
    ]
    stats = build_weekly_stats(
        views,
        settings,
        week_start,
        now_utc,
        global_actions=global_actions,
        day_logs=day_logs,
    )

    # weekly_review_prompt is pure (json.dumps + strings) — kept OUTSIDE the try so
    # a bug there surfaces rather than silently degrading.
    system_prompt, user_prompt = weekly_review_prompt(stats)
    narrative: Optional[str] = None
    try:
        # run_id/task_id stay empty: this is a beat sweep, not a Run. Cost is
        # attributed by call_site="planner_weekly_review" in llm_usage_events
        # (visible in call_site rollups; it won't join Run for run_type rollups).
        set_llm_context(workspace_id=workspace_id, call_site="planner_weekly_review")
        text = get_llm_client().complete_simple(
            system_prompt, user_prompt, max_tokens=_NARRATIVE_MAX_TOKENS
        )
        narrative = text.strip() or None
    except Exception as exc:  # noqa: BLE001
        # The narrative is best-effort: ANY failure — missing key / quota /
        # timeout / a malformed empty-choices response (IndexError escapes the
        # client's LLMCallError guard) — degrades to the number-only template
        # instead of aborting this workspace (and, in the shared-transaction
        # sweep, everyone else's already-generated reviews).
        logger.warning(
            "weekly_review: LLM narrative failed for ws=%s week=%s (degrading): %s",
            workspace_id, week_start, exc,
        )

    return PlannerReviewRepository(session).upsert(
        workspace_id=workspace_id,
        week_start=week_start,
        stats_json=stats.model_dump(),
        narrative_md=narrative,
    )
