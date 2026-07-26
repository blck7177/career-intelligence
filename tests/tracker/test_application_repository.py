"""Repository tests for JobApplicationRepository (create/get/list/transition)."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.domain.applications.transitions import InvalidTransition
from packages.infrastructure.db.repositories import (
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
