"""Repository tests for JobApplicationRepository (create/get/list/transition)."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.domain.applications.transitions import InvalidTransition
from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    ApplicationEventRepository,
    JobApplicationRepository,
)

WS = "ws_test"
OTHER_WS = "ws_other"


def test_create_linked_application(db_session: Session):
    repo = JobApplicationRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="job1", status="planned")
    assert app.id
    assert app.status == "planned"
    assert app.job_id == "job1"


def test_job_id_is_required(db_session: Session):
    # job_id is NOT NULL — the DB rejects a bare/off-platform row. Every
    # application references a job (URL-imported or paste-created).
    repo = JobApplicationRepository(db_session)
    with pytest.raises(IntegrityError):
        repo.create(workspace_id=WS, job_id=None)
    db_session.rollback()


def test_get_is_workspace_scoped(db_session: Session):
    repo = JobApplicationRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="job1")
    assert repo.get(app.id, WS) is not None
    # Cross-workspace read returns None (IDOR guard).
    assert repo.get(app.id, OTHER_WS) is None


def test_unique_per_workspace_job(db_session: Session):
    repo = JobApplicationRepository(db_session)
    repo.create(workspace_id=WS, job_id="job1")
    with pytest.raises(IntegrityError):
        repo.create(workspace_id=WS, job_id="job1")  # dup (workspace, job)
    db_session.rollback()


def test_list_filters_by_status_group(db_session: Session):
    repo = JobApplicationRepository(db_session)
    repo.create(workspace_id=WS, job_id="j1", status="planned")
    repo.create(workspace_id=WS, job_id="j2", status="applied")
    repo.create(workspace_id=WS, job_id="j3", status="rejected")
    assert len(repo.list_for_workspace(WS, status_group="planned")) == 1
    assert len(repo.list_for_workspace(WS, status_group="active")) == 1
    assert len(repo.list_for_workspace(WS, status_group="closed")) == 1
    assert len(repo.list_for_workspace(WS)) == 3
    assert len(repo.list_for_workspace(OTHER_WS)) == 0  # workspace isolation


def test_transition_legal_writes_event_and_stamps_applied_at(db_session: Session):
    repo = JobApplicationRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="planned")
    assert app.applied_at is None
    repo.transition_status(app.id, WS, "applied", note="submitted")
    assert app.status == "applied"
    assert app.applied_at is not None  # stamped on first reach of "applied"
    log = events.list_for_application(app.id, WS)
    assert len(log) == 1
    assert log[0].event_type == "status_changed"
    assert log[0].payload_json["from"] == "planned"
    assert log[0].payload_json["to"] == "applied"


def test_transition_illegal_raises(db_session: Session):
    repo = JobApplicationRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="interviewing")
    with pytest.raises(InvalidTransition):
        repo.transition_status(app.id, WS, "planned")  # backward, no force


def test_transition_force_allows_backward(db_session: Session):
    repo = JobApplicationRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="interviewing")
    repo.transition_status(app.id, WS, "applied", force=True)
    assert app.status == "applied"


def test_transition_cross_workspace_returns_none(db_session: Session):
    repo = JobApplicationRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1")
    assert repo.transition_status(app.id, OTHER_WS, "applied") is None


def test_closing_retires_the_applications_pending_todos(db_session: Session):
    # A follow-up raised the day before a rejection used to keep surfacing on
    # Today forever: nothing cancelled it, and list_due never joins the
    # application. Closing now retires exactly the pending rows.
    repo = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="applied")
    pending_a = actions.create(workspace_id=WS, application_id=app.id, type="follow_up", title="follow up")
    pending_b = actions.create(workspace_id=WS, application_id=app.id, type="prep", title="prep")
    done = actions.create(workspace_id=WS, application_id=app.id, type="apply", title="applied", status="done")
    dismissed = actions.create(
        workspace_id=WS, application_id=app.id, type="thank_you", title="thanks", status="dismissed"
    )

    repo.transition_status(app.id, WS, "ghosted", note="no reply in 15 days")

    assert pending_a.status == "cancelled"
    assert pending_b.status == "cancelled"
    assert done.status == "done"  # history is not rewritten
    assert dismissed.status == "dismissed"  # the user's own veto still stands
    log = events.list_for_application(app.id, WS)
    assert log[-1].payload_json["cancelled_actions"] == 2


def test_closing_only_touches_this_application_in_this_workspace(db_session: Session):
    repo = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="applied")
    other_app = repo.create(workspace_id=WS, job_id="j2", status="applied")
    mine = actions.create(workspace_id=WS, application_id=app.id, type="follow_up", title="mine")
    neighbour = actions.create(workspace_id=WS, application_id=other_app.id, type="follow_up", title="theirs")
    # A global to-do ("refill the queue") has no application and must survive.
    global_row = actions.create(workspace_id=WS, application_id=None, type="global", title="refill")
    # Same application id, different workspace — the IDOR shape this repo guards.
    foreign = actions.create(workspace_id=OTHER_WS, application_id=app.id, type="follow_up", title="foreign")

    repo.transition_status(app.id, WS, "rejected")

    assert mine.status == "cancelled"
    assert neighbour.status == "pending"
    assert global_row.status == "pending"
    assert foreign.status == "pending"


def test_reopening_a_closed_application_leaves_retired_todos_retired(db_session: Session):
    # The detail pane's reopen button (a forced correction out of a closed
    # status) must not un-retire yesterday's work: the rules engine regenerates
    # whatever still applies on the next beat, which is the right answer for a
    # reopen for the same reason it is on any other day. Pinned because
    # "reopen restores everything" is the tempting reading of the button.
    repo = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="applied")
    row = actions.create(workspace_id=WS, application_id=app.id, type="follow_up", title="follow up")
    repo.transition_status(app.id, WS, "ghosted")
    assert row.status == "cancelled"

    reopened = repo.transition_status(app.id, WS, "applied", force=True, note="closed by mistake")

    assert reopened.status == "applied"
    assert row.status == "cancelled"


def test_moving_forward_retires_nothing(db_session: Session):
    repo = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="applied")
    row = actions.create(workspace_id=WS, application_id=app.id, type="follow_up", title="follow up")

    repo.transition_status(app.id, WS, "interviewing")

    assert row.status == "pending"
    assert events.list_for_application(app.id, WS)[-1].payload_json["cancelled_actions"] == 0


def test_update_fields_whitelist(db_session: Session):
    repo = JobApplicationRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1")
    repo.update_fields(app.id, WS, lane="a", excitement=3, notes="great co")
    assert app.lane == "a"
    assert app.excitement == 3
    with pytest.raises(ValueError):
        repo.update_fields(app.id, WS, status="applied")  # status goes via transition
    with pytest.raises(ValueError):
        repo.update_fields(app.id, WS, job_id="hijack")  # immutable, not in allowlist


def test_count_by_status(db_session: Session):
    repo = JobApplicationRepository(db_session)
    repo.create(workspace_id=WS, job_id="j1", status="planned")
    repo.create(workspace_id=WS, job_id="j2", status="planned")
    repo.create(workspace_id=WS, job_id="j3", status="applied")
    assert repo.count_by_status(WS) == {"planned": 2, "applied": 1}


def test_delete_planned_removes_the_application_and_its_rows(db_session: Session):
    repo = JobApplicationRepository(db_session)
    actions = ApplicationActionRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="planned")
    keep = repo.create(workspace_id=WS, job_id="j2", status="planned")
    actions.create(workspace_id=WS, application_id=app.id, type="apply", title="apply")
    events.append(application_id=app.id, workspace_id=WS, event_type="note", message="n")
    kept_action = actions.create(workspace_id=WS, application_id=keep.id, type="apply", title="other")

    assert repo.delete_planned(app.id, WS) is True

    assert repo.get(app.id, WS) is None
    assert events.list_for_application(app.id, WS) == []
    assert actions.list_for_application(app.id, WS) == []
    # The neighbour is untouched — children are matched by application, not swept.
    assert repo.get(keep.id, WS) is not None
    assert kept_action.status == "pending"


def test_delete_refuses_anything_that_was_applied_to(db_session: Session):
    # The line the product draws: mistakes are erasable, history is not. Every
    # non-planned status is counted somewhere the user reads (funnel, interview
    # rate, frozen weekly stats).
    repo = JobApplicationRepository(db_session)
    for i, status in enumerate(["applied", "in_review", "interviewing", "offer", "rejected", "withdrawn", "ghosted"]):
        app = repo.create(workspace_id=WS, job_id=f"job-{i}", status=status)
        assert repo.delete_planned(app.id, WS) is False, status
        assert repo.get(app.id, WS) is not None


def test_delete_is_workspace_scoped(db_session: Session):
    repo = JobApplicationRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="planned")
    assert repo.delete_planned(app.id, OTHER_WS) is False  # IDOR guard
    assert repo.get(app.id, WS) is not None


def test_append_persists_event_at(db_session: Session):
    from datetime import datetime, timezone

    repo = JobApplicationRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="interviewing")
    at = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)
    events.append(
        application_id=app.id,
        workspace_id=WS,
        event_type="interview_scheduled",
        payload_json={"round_type": "onsite", "at": at.isoformat()},
        event_at=at,
    )
    events.append(  # a note has no instant it describes — the column stays NULL
        application_id=app.id, workspace_id=WS, event_type="note", message="hi"
    )
    log = events.list_for_application(app.id, WS)
    stored = {e.event_type: e.event_at for e in log}
    got = stored["interview_scheduled"]
    if got.tzinfo is None:  # SQLite round-trips drop tzinfo; the instant is UTC
        got = got.replace(tzinfo=timezone.utc)
    assert got == at
    assert stored["note"] is None


def test_list_events_between_filters_on_the_column_not_the_payload(db_session: Session):
    """The week window is a SQL predicate over event_at. Three exclusions all
    matter: outside the range, event_at NULL (an interview the backfill could
    not date — it can't sit on a day), and other workspaces."""
    from datetime import datetime, timezone

    repo = JobApplicationRepository(db_session)
    events = ApplicationEventRepository(db_session)
    app = repo.create(workspace_id=WS, job_id="j1", status="interviewing")
    other = repo.create(workspace_id=OTHER_WS, job_id="j1", status="interviewing")

    def _iv(app_row, ws, day, hour=12):
        at = datetime(2026, 8, day, hour, 0, tzinfo=timezone.utc)
        return events.append(
            application_id=app_row.id, workspace_id=ws,
            event_type="interview_scheduled",
            payload_json={"round_type": "onsite", "at": at.isoformat()},
            event_at=at,
        )

    _iv(app, WS, 9)                    # before the window
    inside_late = _iv(app, WS, 12, hour=18)
    inside_early = _iv(app, WS, 11)
    _iv(app, WS, 17)                   # after the window (end-exclusive: the 17th is the next week's Monday)
    # Log order is the OPPOSITE of interview order (a round booked weeks ahead
    # is an old row pointing at a future date). SQLite gives every row the same
    # CURRENT_TIMESTAMP second, and an index-prefix scan then leaks event_at
    # order anyway — distinct values make the ordering assertion load-bearing.
    inside_late.created_at = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    inside_early.created_at = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
    db_session.flush()
    _iv(other, OTHER_WS, 12)           # someone else's interview, same dates
    events.append(                     # undated: event_at NULL never matches a range
        application_id=app.id, workspace_id=WS,
        event_type="interview_scheduled", payload_json={"round_type": "final"},
    )
    events.append(                     # right kind of time, wrong kind of event
        application_id=app.id, workspace_id=WS, event_type="note", message="x",
    )

    start = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    got = events.list_events_between(WS, "interview_scheduled", start, end)
    assert [e.id for e in got] == [inside_early.id, inside_late.id]  # ordered by event_at
