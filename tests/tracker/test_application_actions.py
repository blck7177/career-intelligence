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


def test_snooze_counts_deferrals(db_session: Session):
    """A repeatedly-deferred to-do has to be able to say so — the Today row
    surfaces the count once it climbs."""
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="apply", title="x", due_at=_now())
    assert act.snooze_count == 0  # a real value, not "unknown"
    repo.snooze(act.id, WS, days=1)
    repo.snooze(act.id, WS, days=1)
    repo.snooze(act.id, WS, days=1)
    assert act.snooze_count == 3


def test_snooze_until_counts_when_it_pushes_later(db_session: Session):
    # Rest-until-Monday takes the absolute-target branch; pushing later counts.
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="apply", title="x", due_at=_now())
    repo.snooze(act.id, WS, until=_now() + timedelta(days=4))
    assert act.snooze_count == 1


def test_snooze_does_not_count_when_it_pulls_earlier(db_session: Session):
    """Rest-until-Monday applies one absolute target to every visible action, so
    anything due after that Monday gets pulled EARLIER. Counting those would
    inflate the number on rows nobody put off — two taps and the whole list
    would claim to be repeatedly deferred."""
    repo = ApplicationActionRepository(db_session)
    now = _now()
    far = repo.create(workspace_id=WS, type="prep", title="future", due_at=now + timedelta(days=10))
    repo.snooze(far.id, WS, until=now + timedelta(days=3))
    assert far.due_at < now + timedelta(days=10)  # it did move
    assert far.snooze_count == 0  # ...but earlier is not a deferral


def test_count_pending_carried_into_today(db_session: Session):
    """What weighs on today without being due today: overdue and undated work.
    Today's own dues must NOT be included — the week-range query already has
    them, and counting both would double them on the strip."""
    repo = ApplicationActionRepository(db_session)
    today_start = datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)  # 00:00 EDT
    repo.create(workspace_id=WS, type="apply", title="overdue",
                due_at=today_start - timedelta(days=5))
    repo.create(workspace_id=WS, type="custom", title="undated")
    repo.create(workspace_id=WS, type="apply", title="due today", due_at=today_start)
    repo.create(workspace_id=WS, type="apply", title="later",
                due_at=today_start + timedelta(days=3))
    done = repo.create(workspace_id=WS, type="apply", title="already done",
                       due_at=today_start - timedelta(days=2))
    repo.complete(done.id, WS)
    # Another workspace's backlog must not leak in.
    repo.create(workspace_id=OTHER_WS, type="apply", title="theirs",
                due_at=today_start - timedelta(days=1))

    assert repo.count_pending_carried_into_today(WS, today_start) == 2


def test_snooze_counts_undated_work(db_session: Session):
    # Giving "anytime" work tomorrow's date postpones something available today.
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="custom", title="someday")
    repo.snooze(act.id, WS, days=1)
    assert act.snooze_count == 1


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
