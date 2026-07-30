"""planner_run — the daily Celery beat task.

Runs the pure rules engine (packages/domain/planner/rules.py) for every workspace
that has a tracker and persists the generated auto-actions. Zero LLM, zero cost.
Idempotent: the engine won't re-emit an action a pending/dismissed one already
suppresses, so re-running the daily beat produces no duplicates.

`run_daily_rules_once(session, now_utc)` is the testable core (inject a session +
clock); the Celery task wraps it with get_session() + the real UTC clock.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apps.worker.celery_app import celery_app
from packages.domain.planner.rules import ApplicationView, generate_actions, is_rest_day
from packages.domain.planner.settings import load_planner_settings
from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    ApplicationEventRepository,
    JobApplicationRepository,
    WorkspaceRepository,
)
from packages.infrastructure.db.session import get_session
from packages.infrastructure.planner_mapping import action_view, application_view

logger = logging.getLogger(__name__)


def run_for_workspace(session: Any, workspace_id: str, now_utc: datetime) -> int:
    """Generate + persist auto-actions for one workspace; returns count created."""
    workspace = WorkspaceRepository(session).get(workspace_id)
    if workspace is None:
        return 0
    settings = load_planner_settings(workspace)
    app_repo = JobApplicationRepository(session)
    event_repo = ApplicationEventRepository(session)
    action_repo = ApplicationActionRepository(session)

    views: list[ApplicationView] = [
        application_view(
            app,
            event_repo.list_for_application(app.id, workspace_id),
            action_repo.list_for_application(app.id, workspace_id),
        )
        for app in app_repo.list_for_workspace(workspace_id, limit=10_000)
    ]
    global_actions = [action_view(a) for a in action_repo.list_global_for_workspace(workspace_id)]

    specs = generate_actions(
        applications=views,
        settings=settings,
        now_utc=now_utc,
        global_actions=global_actions,
    )
    for spec in specs:
        action_repo.create(
            workspace_id=workspace_id,
            type=spec.type,
            title=spec.title,
            application_id=spec.application_id,
            due_at=spec.due_at,
            auto_generated=True,
            payload_json=spec.payload,
            est_minutes=spec.est_minutes,
        )
    return len(specs)


def run_daily_rules_once(session: Any, now_utc: datetime) -> dict:
    """One full sweep across every workspace with applications. Rows are flushed
    (visible in-session); the caller's transaction boundary commits them —
    get_session() in the task, the test's fixture in tests.

    Workspaces whose local today is a rest day are skipped here, before their
    snapshot is loaded — that load is the expensive part (a query per
    application). `generate_actions` refuses to emit on a rest day anyway, so
    this is the cheap path, not the rule. Resting workspaces are counted
    separately so the beat's log line can tell "nobody was ripe" apart from
    "everybody was off"; without it a quiet Saturday looks like a broken beat."""
    ws_repo = WorkspaceRepository(session)
    ws_ids = JobApplicationRepository(session).list_workspace_ids_with_applications()
    created = 0
    resting = 0
    for ws_id in ws_ids:
        workspace = ws_repo.get(ws_id)
        if workspace is not None and is_rest_day(load_planner_settings(workspace), now_utc):
            resting += 1
            continue
        created += run_for_workspace(session, ws_id, now_utc)
    return {"workspaces": len(ws_ids), "resting": resting, "actions_created": created}


@celery_app.task(name="apps.worker.tasks.planner_run.run_daily_rules", max_retries=0)
def run_daily_rules() -> dict:
    now_utc = datetime.now(timezone.utc)
    with get_session() as session:
        result = run_daily_rules_once(session, now_utc)
    logger.info("planner_run: %s", result)
    return result


def run_weekly_review_once(session: Any, now_utc: datetime) -> dict:
    """Generate + upsert a weekly review for every workspace with applications.
    Each workspace's reviewed week is the Monday of its own local week
    (settings.timezone), so a single Sunday-night UTC schedule serves all zones.
    LLM failures degrade per-workspace (NULL narrative), never aborting the
    sweep. Rows are flushed; the caller's transaction commits them."""
    from packages.infrastructure.services.weekly_review_service import (
        generate_weekly_review,
    )

    ws_ids = JobApplicationRepository(session).list_workspace_ids_with_applications()
    generated = 0
    for ws_id in ws_ids:
        try:
            if generate_weekly_review(session, ws_id, now_utc=now_utc) is not None:
                generated += 1
        except Exception:  # noqa: BLE001
            # One workspace's hard failure must not abort the sweep. The LLM path
            # already degrades internally; this guards any other per-workspace
            # error (bad data, a DB hiccup on one row) so the rest still generate.
            logger.exception("weekly_review: workspace %s failed; continuing sweep", ws_id)
    return {"workspaces": len(ws_ids), "reviews_generated": generated}


@celery_app.task(name="apps.worker.tasks.planner_run.run_weekly_review", max_retries=0)
def run_weekly_review() -> dict:
    now_utc = datetime.now(timezone.utc)
    with get_session() as session:
        result = run_weekly_review_once(session, now_utc)
    logger.info("planner_run.weekly: %s", result)
    return result
