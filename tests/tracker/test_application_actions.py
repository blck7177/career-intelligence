"""Repository tests for ApplicationActionRepository (the planner's Today table)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    ApplicationEventRepository,
    JobApplicationRepository,
)

WS = "ws_test"
OTHER_WS = "ws_other"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_create_and_get_action(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="follow_up", title="Ping recruiter")
    assert act.status == "pending"
    assert repo.get(act.id, WS) is not None
    assert repo.get(act.id, OTHER_WS) is None  # workspace-scoped


def test_create_persists_est_minutes(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    estimated = repo.create(workspace_id=WS, type="apply", title="with est", est_minutes=60)
    assert estimated.est_minutes == 60
    # Omitted → NULL, never 0: consumers fall back to a per-type default.
    unestimated = repo.create(workspace_id=WS, type="apply", title="no est")
    assert unestimated.est_minutes is None


def test_list_due_includes_overdue_and_undated_excludes_future(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    now = _now()
    overdue = repo.create(
        workspace_id=WS, type="apply", title="overdue", due_at=now - timedelta(days=1)
    )
    undated = repo.create(workspace_id=WS, type="custom", title="someday")
    future = repo.create(
        workspace_id=WS, type="apply", title="later", due_at=now + timedelta(days=3)
    )
    ids = {a.id for a in repo.list_due(WS, now)}
    assert overdue.id in ids
    assert undated.id in ids  # undated included by default
    assert future.id not in ids
    # And excluded when the caller opts out of undated actions.
    assert undated.id not in {a.id for a in repo.list_due(WS, now, include_undated=False)}


def test_complete_writes_event_on_application(db_session: Session):
    apps = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = apps.create(workspace_id=WS, job_id="j1")
    act = actions.create(
        workspace_id=WS, application_id=app.id, type="follow_up", title="follow up"
    )
    actions.complete(act.id, WS)
    assert act.status == "done"
    assert act.completed_at is not None
    log = events.list_for_application(app.id, WS)
    assert any(e.event_type == "action_completed" for e in log)


def test_complete_global_action_no_event(db_session: Session):
    actions = ApplicationActionRepository(db_session)
    act = actions.create(workspace_id=WS, type="global", title="run discovery")
    done = actions.complete(act.id, WS)
    assert done.status == "done"  # no application_id -> no event, no crash


def test_snooze_pushes_due_at(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    now = _now()
    act = repo.create(workspace_id=WS, type="apply", title="x", due_at=now - timedelta(days=1))
    repo.snooze(act.id, WS, days=2)
    assert act.due_at > now
    assert act.status == "pending"
    assert act.id not in {a.id for a in repo.list_due(WS, now)}  # now in the future


def test_dismiss(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="custom", title="x")
    repo.dismiss(act.id, WS)
    assert act.status == "dismissed"
    assert repo.count_due(WS, _now()) == 0


def test_count_due(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    now = _now()
    repo.create(workspace_id=WS, type="apply", title="a", due_at=now - timedelta(days=1))
    repo.create(workspace_id=WS, type="apply", title="b")  # undated -> counts
    repo.create(workspace_id=WS, type="apply", title="c", due_at=now + timedelta(days=5))
    assert repo.count_due(WS, now) == 2
