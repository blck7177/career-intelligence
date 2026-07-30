"""Task-level test for the planner daily beat (W2-C2): inject an in-memory
session + fixed clock, run a real sweep, assert actions land and re-running is
idempotent (no duplicates, dismissed stays dead)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.worker.tasks.planner_run import run_daily_rules_once
from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    ApplicationEventRepository,
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


def test_planner_run_adds_no_debt_on_a_rest_day(db_session):
    """rest_days = today → the sweep generates nothing and says so. NOW is a
    Wednesday, so ["wed"] is "today is a day off"."""
    ws_repo = WorkspaceRepository(db_session)
    ws_repo.create(name="t", workspace_id="ws4")
    ws_repo.set_planner_settings("ws4", {"rest_days": ["wed"]})
    app_repo = JobApplicationRepository(db_session)
    app = app_repo.create(
        workspace_id="ws4", job_id="j1", status="applied", applied_at=APPLIED_8D
    )
    db_session.flush()

    r = run_daily_rules_once(db_session, NOW)

    assert r == {"workspaces": 1, "resting": 1, "actions_created": 0}
    action_repo = ApplicationActionRepository(db_session)
    assert action_repo.list_for_application(app.id, "ws4") == []
    # The global refill is the load-bearing assertion: unlike the per-application
    # rules it can never be suppressed by an existing row, so it would appear if
    # the rest day were ignored.
    assert action_repo.list_global_for_workspace("ws4") == []

    # Thursday: same workspace, same data, the beat resumes. Without this the test
    # would also pass against a sweep that was simply broken.
    r2 = run_daily_rules_once(db_session, NOW + timedelta(days=1))
    assert r2["resting"] == 0
    assert r2["actions_created"] == 2  # follow_up + queue_refill
    assert [a.type for a in action_repo.list_for_application(app.id, "ws4")] == ["follow_up"]


def test_rest_day_does_not_hide_work_already_due(db_session):
    """A rest day means no NEW debt, not hidden work: a to-do that came due before
    the day off is still there afterwards, untouched."""
    ws_repo = WorkspaceRepository(db_session)
    ws_repo.create(name="t", workspace_id="ws5")
    ws_repo.set_planner_settings("ws5", {"rest_days": ["wed"]})
    app_repo = JobApplicationRepository(db_session)
    app = app_repo.create(
        workspace_id="ws5", job_id="j1", status="applied", applied_at=APPLIED_8D
    )
    action_repo = ApplicationActionRepository(db_session)
    due_yesterday = action_repo.create(
        workspace_id="ws5", type="follow_up", title="from tuesday",
        application_id=app.id, due_at=NOW - timedelta(days=1), auto_generated=True,
    )
    db_session.flush()

    run_daily_rules_once(db_session, NOW)

    rows = action_repo.list_for_application(app.id, "ws5")
    assert [r.id for r in rows] == [due_yesterday.id]
    assert rows[0].status == "pending"
    assert rows[0].due_at == due_yesterday.due_at


def test_resting_workspace_does_not_stop_the_sweep(db_session):
    """One workspace resting must be a skip, not an exit — `break` where
    `continue` belongs would silently starve every workspace after it. Asserted
    per workspace because the sweep's iteration order is not specified."""
    ws_repo = WorkspaceRepository(db_session)
    app_repo = JobApplicationRepository(db_session)
    for ws_id in ("ws6-rest", "ws7-work"):
        ws_repo.create(name=ws_id, workspace_id=ws_id)
        app_repo.create(workspace_id=ws_id, job_id="j1", status="applied", applied_at=APPLIED_8D)
    ws_repo.set_planner_settings("ws6-rest", {"rest_days": ["wed"]})
    db_session.flush()

    r = run_daily_rules_once(db_session, NOW)

    assert r == {"workspaces": 2, "resting": 1, "actions_created": 2}
    action_repo = ApplicationActionRepository(db_session)
    assert action_repo.list_global_for_workspace("ws6-rest") == []
    assert len(action_repo.list_global_for_workspace("ws7-work")) == 1


def test_thank_you_still_lands_on_a_rest_day(db_session):
    """End-to-end counterpart to the engine test: the sweep must NOT short-circuit
    a resting workspace, because the one perishable rule still has to run. An
    earlier version of this wave skipped the workspace before loading its
    snapshot and silently swallowed every Friday-interview thank-you note."""
    ws_repo = WorkspaceRepository(db_session)
    ws_repo.create(name="t", workspace_id="ws8")
    ws_repo.set_planner_settings("ws8", {"rest_days": ["sat", "sun"]})
    app_repo = JobApplicationRepository(db_session)
    app = app_repo.create(workspace_id="ws8", job_id="j1", status="interviewing", applied_at=APPLIED_8D)
    interview = datetime(2026, 7, 17, 20, 0, tzinfo=timezone.utc)  # Fri 16:00 EDT
    ApplicationEventRepository(db_session).append(
        workspace_id="ws8", application_id=app.id, event_type="interview_scheduled",
        payload_json={"at": interview.isoformat(), "round_type": "onsite"},
    )
    db_session.flush()

    saturday_beat = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)
    r = run_daily_rules_once(db_session, saturday_beat)

    assert r["resting"] == 1  # it IS a rest day...
    assert r["actions_created"] == 1  # ...and the perishable rule still ran
    rows = ApplicationActionRepository(db_session).list_for_application(app.id, "ws8")
    assert [a.type for a in rows] == ["thank_you"]
    # Due MONDAY, not Saturday: the reminder is kept without disturbing the day
    # off. (SQLite drops tzinfo on round-trip; compare the instant.)
    due = rows[0].due_at
    due = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
    assert due == datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)  # Mon 00:00 EDT
