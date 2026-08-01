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
