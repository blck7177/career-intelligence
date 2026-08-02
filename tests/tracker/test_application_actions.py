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


def test_list_pending_carried_into_today(db_session: Session):
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

    rows = repo.list_pending_carried_into_today(WS, today_start)
    # The strip reads both the count and the minutes off this one row set, which
    # is why it returns rows at all: two queries could answer these separately
    # and drift apart the first time one grew a condition the other did not.
    # Only the two columns the caller reads come back.
    from packages.domain.planner.rules import effective_est_minutes

    assert len(rows) == 2
    assert {t for t, _ in rows} == {"apply", "custom"}
    assert sum(effective_est_minutes(t, e) for t, e in rows) == 80  # apply 60 + custom 20


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


def test_earliest_pending_action_map_breaks_ties_on_id(db_session: Session):
    """Two to-dos due the same day must resolve to the same one every time.

    Due dates are local midnights, so a follow-up and a thank-you both landing on
    Tuesday is ordinary rather than exotic. With `order_by(due_at)` alone the
    winner was whatever the database returned first — and the Applications row's
    "Reschedule" button re-derives this same choice client-side in order to move
    the to-do the row is *showing*, so an undefined tie makes that a coin flip.
    """
    apps = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    app = apps.create(workspace_id=WS, job_id="j-tie")
    same_day = _now() + timedelta(days=2)
    types = ("follow_up", "thank_you", "networking", "apply", "custom")

    # Ids are random, so keep adding same-day rows until the smallest id is NOT
    # the row created first. Without that the database's natural (insertion)
    # order would satisfy the assertion on its own and the test could not fail
    # if the tie-break were removed.
    made: list = []
    while not made or min(made, key=lambda a: a.id) is made[0]:
        made.append(
            actions.create(
                workspace_id=WS,
                application_id=app.id,
                type=types[len(made) % len(types)],
                title=f"tie-{len(made)}",
                due_at=same_day,
            )
        )
    expected = min(made, key=lambda a: a.id)

    for _ in range(3):
        assert actions.earliest_pending_action_map(WS, [app.id])[app.id][1] == expected.type

    # An earlier due date still wins outright — the tie-break is secondary.
    sooner = actions.create(
        workspace_id=WS,
        application_id=app.id,
        type="global",
        title="sooner",
        due_at=same_day - timedelta(days=1),
    )
    assert actions.earliest_pending_action_map(WS, [app.id])[app.id][1] == sooner.type


def test_reopen_restores_an_undated_todo_exactly(db_session: Session):
    """The case a snooze cannot express, and the reason `reopen` is its own op.

    An undated to-do has no due_at to restore, so undoing its completion via
    snooze would invent one (`now + 1 day`) and count the restoration as a
    postponement. Reopen puts the row back the way it was.
    """
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="custom", title="anytime")
    repo.complete(act.id, WS)
    assert act.status == "done"

    repo.reopen(act.id, WS)

    assert act.status == "pending"
    assert act.completed_at is None
    assert act.due_at is None  # not invented
    assert act.snooze_count == 0  # undoing is not deferring


def test_reopen_removes_the_completion_it_undoes(db_session: Session):
    """The completion event is what `_check_in` and the check-in alert measure
    staleness from. Leaving it would keep the nudge the user just restored
    suppressed for days."""
    apps = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = apps.create(workspace_id=WS, job_id="j1")
    act = actions.create(workspace_id=WS, application_id=app.id, type="prep", title="check in")
    other = actions.create(workspace_id=WS, application_id=app.id, type="follow_up", title="ping")
    actions.complete(act.id, WS)
    actions.complete(other.id, WS)
    assert len([e for e in events.list_for_application(app.id, WS) if e.event_type == "action_completed"]) == 2

    actions.reopen(act.id, WS)
    db_session.flush()

    remaining = [e for e in events.list_for_application(app.id, WS) if e.event_type == "action_completed"]
    # Only the undone one goes; the other completion is untouched.
    assert len(remaining) == 1
    assert remaining[0].payload_json["action_id"] == other.id


def test_reopen_is_idempotent_and_workspace_scoped(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="custom", title="x", due_at=_now())
    due = act.due_at

    repo.reopen(act.id, WS)  # never completed — nothing to undo
    assert act.status == "pending"
    assert act.due_at == due

    repo.complete(act.id, WS)
    assert repo.reopen(act.id, OTHER_WS) is None  # IDOR guard
    assert act.status == "done"


def test_reopen_a_global_action_has_no_event_to_remove(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="global", title="refill the queue")
    repo.complete(act.id, WS)
    repo.reopen(act.id, WS)
    assert act.status == "pending"  # no application_id -> no event, no crash


def test_completing_twice_is_a_no_op(db_session: Session):
    # Two tabs or a retried PATCH used to move completed_at and append a second
    # event — which then survived a reopen and left the timeline claiming a
    # completion for an open to-do.
    apps = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = apps.create(workspace_id=WS, job_id="j1")
    act = actions.create(workspace_id=WS, application_id=app.id, type="follow_up", title="ping")
    actions.complete(act.id, WS)
    first = act.completed_at

    actions.complete(act.id, WS)

    assert act.completed_at == first
    assert len([e for e in events.list_for_application(app.id, WS) if e.event_type == "action_completed"]) == 1


def test_reopen_removes_every_completion_event_for_that_action(db_session: Session):
    # Historical rows completed twice (before complete() was idempotent) carry
    # duplicates; leaving one behind keeps the check-in clock reset.
    apps = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = apps.create(workspace_id=WS, job_id="j1")
    act = actions.create(workspace_id=WS, application_id=app.id, type="prep", title="check in")
    actions.complete(act.id, WS)
    # Simulate the pre-fix duplicate directly, since complete() now refuses to.
    events.append(
        application_id=app.id, workspace_id=WS, event_type="action_completed",
        message=act.title, payload_json={"action_id": act.id, "type": act.type},
    )
    assert len([e for e in events.list_for_application(app.id, WS) if e.event_type == "action_completed"]) == 2

    actions.reopen(act.id, WS)
    db_session.flush()

    assert [e for e in events.list_for_application(app.id, WS) if e.event_type == "action_completed"] == []


# --- scheduling (V8: the week grid's "which day, what time") -----------------


def test_schedule_places_a_todo_without_touching_its_due_date(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    due = _now() + timedelta(days=3)
    act = repo.create(workspace_id=WS, type="apply", title="Apply · HRT", due_at=due)
    assert act.scheduled_at is None  # a fresh to-do starts in the tray

    at = _now() + timedelta(days=1)
    repo.schedule(act.id, WS, at)

    assert act.scheduled_at == at
    # The day it is OWED is a different fact from the day the user set aside to
    # do it; scheduling one must not silently move the other.
    assert act.due_at == due
    assert act.snooze_count == 0


def test_scheduling_earlier_than_the_due_date_is_not_a_postponement(db_session: Session):
    # The bug this guards: routing schedule through snooze() would bump
    # snooze_count and report a deferral for work the user actually pulled
    # FORWARD — the same confusion V5-C7 had to unpick for Rest-until-Monday.
    repo = ApplicationActionRepository(db_session)
    act = repo.create(
        workspace_id=WS, type="apply", title="early", due_at=_now() + timedelta(days=5)
    )
    repo.schedule(act.id, WS, _now() + timedelta(days=1))
    assert act.snooze_count == 0


def test_unschedule_returns_it_to_the_tray_still_owed(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    due = _now() + timedelta(days=2)
    act = repo.create(workspace_id=WS, type="follow_up", title="ping", due_at=due)
    repo.schedule(act.id, WS, _now())
    repo.unschedule(act.id, WS)
    assert act.scheduled_at is None
    # Clearing due_at too would turn "I'll find another time" into "not due".
    assert act.due_at == due
    assert act.status == "pending"


def test_schedule_and_unschedule_are_workspace_scoped(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    act = repo.create(workspace_id=WS, type="apply", title="mine")
    assert repo.schedule(act.id, OTHER_WS, _now()) is None
    assert repo.unschedule(act.id, OTHER_WS) is None
    assert act.scheduled_at is None  # the foreign call changed nothing


def test_list_scheduled_between_is_half_open_and_ordered(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    start = datetime(2026, 8, 3, tzinfo=timezone.utc)
    end = start + timedelta(days=7)

    late = repo.create(workspace_id=WS, type="apply", title="thu")
    repo.schedule(late.id, WS, start + timedelta(days=3, hours=14))
    early = repo.create(workspace_id=WS, type="apply", title="mon")
    repo.schedule(early.id, WS, start + timedelta(hours=9))
    on_start = repo.create(workspace_id=WS, type="apply", title="on start")
    repo.schedule(on_start.id, WS, start)
    on_end = repo.create(workspace_id=WS, type="apply", title="on end")
    repo.schedule(on_end.id, WS, end)
    unplaced = repo.create(workspace_id=WS, type="apply", title="tray")

    rows = repo.list_scheduled_between(WS, start, end)
    ids = [r.id for r in rows]
    # [start, end): the boundary instant belongs to the NEXT week, or a block
    # would be counted twice when the grid pages forward.
    assert on_start.id in ids
    assert on_end.id not in ids
    assert unplaced.id not in ids
    assert ids.index(early.id) < ids.index(late.id)


def test_a_finished_block_still_shows_how_the_day_was_spent(db_session: Session):
    # Dropping completed blocks would make a day look emptier the more got done.
    repo = ApplicationActionRepository(db_session)
    start = datetime(2026, 8, 3, tzinfo=timezone.utc)
    act = repo.create(workspace_id=WS, type="apply", title="done one")
    repo.schedule(act.id, WS, start + timedelta(hours=10))
    repo.complete(act.id, WS)
    assert act.id in {r.id for r in repo.list_scheduled_between(WS, start, start + timedelta(days=7))}


def test_dismissed_and_retired_blocks_leave_the_grid(db_session: Session):
    from packages.domain.planner.rules import RETIRED_STATUS

    repo = ApplicationActionRepository(db_session)
    start = datetime(2026, 8, 3, tzinfo=timezone.utc)
    dropped = repo.create(workspace_id=WS, type="apply", title="dropped")
    repo.schedule(dropped.id, WS, start + timedelta(hours=10))
    repo.dismiss(dropped.id, WS)
    retired = repo.create(workspace_id=WS, type="apply", title="retired")
    repo.schedule(retired.id, WS, start + timedelta(hours=11))
    retired.status = RETIRED_STATUS
    db_session.flush()

    ids = {r.id for r in repo.list_scheduled_between(WS, start, start + timedelta(days=7))}
    assert dropped.id not in ids
    assert retired.id not in ids


def test_list_unscheduled_is_the_tray_soonest_first(db_session: Session):
    repo = ApplicationActionRepository(db_session)
    now = _now()
    undated = repo.create(workspace_id=WS, type="custom", title="someday")
    later = repo.create(workspace_id=WS, type="apply", title="later", due_at=now + timedelta(days=4))
    sooner = repo.create(workspace_id=WS, type="apply", title="sooner", due_at=now + timedelta(days=1))
    placed = repo.create(workspace_id=WS, type="apply", title="placed", due_at=now)
    repo.schedule(placed.id, WS, now)
    done = repo.create(workspace_id=WS, type="apply", title="done")
    repo.complete(done.id, WS)

    ids = [a.id for a in repo.list_unscheduled(WS)]
    assert placed.id not in ids  # already on the calendar
    assert done.id not in ids  # not pending
    assert ids.index(sooner.id) < ids.index(later.id)
    assert ids.index(undated.id) == len(ids) - 1  # undated sorts last
