"""Task-level test for the planner daily beat (W2-C2): inject an in-memory
session + fixed clock, run a real sweep, assert actions land and re-running is
idempotent (no duplicates, dismissed stays dead)."""
from __future__ import annotations

from datetime import datetime, timezone

from apps.worker.tasks.planner_run import run_daily_rules_once
from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    JobApplicationRepository,
    WorkspaceRepository,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
APPLIED_8D = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
PLANNED_15D = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


def test_planner_run_creates_then_idempotent(db_session):
    WorkspaceRepository(db_session).create(name="t", workspace_id="ws1")
    app_repo = JobApplicationRepository(db_session)
    app = app_repo.create(workspace_id="ws1", job_id="j1", status="applied", applied_at=APPLIED_8D)
    db_session.flush()

    r1 = run_daily_rules_once(db_session, NOW)
    assert r1["workspaces"] == 1
    # follow_up (applied 8d ago ≥ 7) + queue_refill global (0 planned < weekly apply 10)
    assert r1["actions_created"] == 2

    action_repo = ApplicationActionRepository(db_session)
    app_actions = action_repo.list_for_application(app.id, "ws1")
    assert [a.type for a in app_actions] == ["follow_up"]
    assert app_actions[0].auto_generated is True
    assert app_actions[0].due_at is not None
    # The engine's per-type estimate reaches the row (Today totals it vs the cap).
    assert app_actions[0].est_minutes == 15
    globals_ = action_repo.list_global_for_workspace("ws1")
    assert len(globals_) == 1
    assert globals_[0].payload_json["rule"] == "queue_refill"
    assert globals_[0].est_minutes == 15

    # Re-run the same day → no duplicates.
    r2 = run_daily_rules_once(db_session, NOW)
    assert r2["actions_created"] == 0
    assert len(action_repo.list_for_application(app.id, "ws1")) == 1
    assert len(action_repo.list_global_for_workspace("ws1")) == 1


def test_planner_run_carries_per_type_estimates(db_session):
    """Two rules with DIFFERENT estimates in one sweep. The other worker test
    only sees 15-minute rules, so a hardcoded `est_minutes=15` in planner_run
    would still pass there — this one pins the value to the rule that fired."""
    WorkspaceRepository(db_session).create(name="t", workspace_id="ws3")
    app_repo = JobApplicationRepository(db_session)
    followed = app_repo.create(
        workspace_id="ws3", job_id="j1", status="applied", applied_at=APPLIED_8D
    )
    stale_plan = app_repo.create(workspace_id="ws3", job_id="j2", status="planned")
    # created_at is a server default, so age the row explicitly for apply_or_drop.
    stale_plan.created_at = PLANNED_15D
    db_session.flush()

    run_daily_rules_once(db_session, NOW)

    action_repo = ApplicationActionRepository(db_session)
    by_type = {
        a.type: a
        for a in action_repo.list_for_application(followed.id, "ws3")
        + action_repo.list_for_application(stale_plan.id, "ws3")
    }
    assert by_type["follow_up"].est_minutes == 15
    assert by_type["apply"].est_minutes == 60  # apply_or_drop, a different default


def test_planner_run_respects_dismissed(db_session):
    WorkspaceRepository(db_session).create(name="t", workspace_id="ws2")
    app_repo = JobApplicationRepository(db_session)
    app = app_repo.create(workspace_id="ws2", job_id="j1", status="applied", applied_at=APPLIED_8D)
    action_repo = ApplicationActionRepository(db_session)
    # The user dismissed a prior auto follow_up.
    action_repo.create(
        workspace_id="ws2", type="follow_up", title="Follow up",
        application_id=app.id, auto_generated=True, status="dismissed",
    )
    db_session.flush()

    run_daily_rules_once(db_session, NOW)

    follow_ups = [a for a in action_repo.list_for_application(app.id, "ws2") if a.type == "follow_up"]
    assert len(follow_ups) == 1  # not resurrected
    assert follow_ups[0].status == "dismissed"
