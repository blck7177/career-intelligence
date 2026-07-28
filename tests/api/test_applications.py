"""API tests for the application tracker routes.

Follows the repo's API-test harness: override get_db (MagicMock) +
get_current_workspace (SimpleNamespace), patch repositories at the ROUTE module
path, TestClient(raise_server_exceptions=False), clear overrides in teardown.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import get_args
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

WS_ID = "ws-app-test"
_NOW = datetime.now(timezone.utc)


def _ws() -> SimpleNamespace:
    return SimpleNamespace(
        id=WS_ID, name="test", tier="beta", created_at=_NOW, updated_at=_NOW,
        planner_settings_json=None,
    )


def _job(**over) -> SimpleNamespace:
    base = dict(
        id="job-1", title="Risk Analyst", company="Example Bank",
        canonical_url="https://example.com/jobs/1", status="reportable",
        discovered_run_id="run-1",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _app(**over) -> SimpleNamespace:
    base = dict(
        id="app-1", workspace_id=WS_ID, job_id="job-1", profile_id=None,
        status="planned", lane=None, excitement=None, channel=None,
        applied_at=None, resume_run_id=None, contact_name=None, contact_note=None,
        notes=None, closed_reason=None, created_at=_NOW, updated_at=_NOW,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _event(**over) -> SimpleNamespace:
    base = dict(id="ev-1", event_type="status_changed", message="submitted",
                payload_json={"from": "planned", "to": "applied"}, created_at=_NOW)
    base.update(over)
    return SimpleNamespace(**base)


def _action(**over) -> SimpleNamespace:
    base = dict(id="act-1", application_id="app-1", type="follow_up", title="Ping",
                due_at=_NOW, est_minutes=15, snooze_count=0, payload_json=None,
                status="pending", auto_generated=False,
                completed_at=None, created_at=_NOW, updated_at=_NOW)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture()
def make_client():
    from apps.api.dependencies.auth import get_current_workspace
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _factory():
        def _mock_db():
            yield MagicMock()

        app.dependency_overrides[get_db] = _mock_db
        app.dependency_overrides[get_current_workspace] = _ws
        return TestClient(app, raise_server_exceptions=False)

    yield _factory
    app.dependency_overrides.clear()


# --- create -----------------------------------------------------------------


class TestCreate:
    def test_create_returns_201_and_stamps_applied_at(self, make_client):
        client = make_client()
        created = _app(id="app-9", status="applied", applied_at=None)
        with patch("apps.api.routes.applications._job_in_workspace", return_value=_job()), \
             patch("apps.api.routes.applications.JobApplicationRepository") as MockRepo:
            MockRepo.return_value.get_by_job.return_value = None
            MockRepo.return_value.create.return_value = created
            resp = client.post(
                "/api/app/applications", json={"job_id": "job-1", "status": "applied"}
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"] == "app-9"
        assert body["job"]["company"] == "Example Bank"
        assert body["applied_at"] is not None  # stamped on direct "applied" create

    def test_create_duplicate_returns_409(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications._job_in_workspace", return_value=_job()), \
             patch("apps.api.routes.applications.JobApplicationRepository") as MockRepo:
            MockRepo.return_value.get_by_job.return_value = _app(id="existing")
            resp = client.post("/api/app/applications", json={"job_id": "job-1"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["existing_application_id"] == "existing"

    def test_create_rejects_job_from_other_workspace(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobRepository") as MockJob, \
             patch("apps.api.routes.applications.RunRepository") as MockRun:
            MockJob.return_value.get.return_value = _job(discovered_run_id="run-x")
            MockRun.return_value.get.return_value = SimpleNamespace(
                id="run-x", workspace_id="SOME-OTHER-WS"
            )
            resp = client.post("/api/app/applications", json={"job_id": "job-1"})
        assert resp.status_code == 404  # enumeration-safe

    def test_create_rejects_foreign_profile_id(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications._job_in_workspace", return_value=_job()), \
             patch("apps.api.routes.applications.ProfileRepository") as MockProfile:
            MockProfile.return_value.get_by_id.return_value = SimpleNamespace(
                id="prof-x", workspace_id="SOME-OTHER-WS"
            )
            resp = client.post(
                "/api/app/applications", json={"job_id": "job-1", "profile_id": "prof-x"}
            )
        assert resp.status_code == 403


# --- list / detail / summary ------------------------------------------------


class TestReads:
    def test_list_returns_items_with_job_and_due(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.JobRepository") as MockJob, \
             patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockApp.return_value.list_for_workspace.return_value = [_app()]
            MockJob.return_value.get.return_value = _job()
            MockAct.return_value.earliest_pending_action_map.return_value = {"app-1": (_NOW, "follow_up")}
            resp = client.get("/api/app/applications?status_group=planned")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["job"]["title"] == "Risk Analyst"
        assert body["items"][0]["next_action_due_at"] is not None
        assert body["items"][0]["next_action_type"] == "follow_up"

    def test_list_include_fit_populates_fit_score(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.JobRepository") as MockJob, \
             patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct, \
             patch("apps.api.routes.applications.FitReportRepository") as MockFit:
            MockApp.return_value.list_for_workspace.return_value = [_app()]
            MockJob.return_value.get.return_value = _job()
            MockAct.return_value.earliest_pending_action_map.return_value = {}
            MockFit.return_value.latest_score_map.return_value = {"job-1": 86}
            resp = client.get("/api/app/applications?status_group=planned&include_fit=true")
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"][0]["fit_score"] == 86
        MockFit.return_value.latest_score_map.assert_called_once()

    def test_list_default_omits_fit(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.JobRepository") as MockJob, \
             patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct, \
             patch("apps.api.routes.applications.FitReportRepository") as MockFit:
            MockApp.return_value.list_for_workspace.return_value = [_app()]
            MockJob.return_value.get.return_value = _job()
            MockAct.return_value.earliest_pending_action_map.return_value = {}
            resp = client.get("/api/app/applications")
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"][0]["fit_score"] is None
        MockFit.return_value.latest_score_map.assert_not_called()

    def test_detail_includes_events_and_actions(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.JobRepository") as MockJob, \
             patch("apps.api.routes.applications.ApplicationEventRepository") as MockEv, \
             patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct, \
             patch("apps.api.routes.applications.FitReportRepository") as MockFit:
            MockApp.return_value.get.return_value = _app()
            MockJob.return_value.get.return_value = _job()
            MockEv.return_value.list_for_application.return_value = [_event()]
            MockAct.return_value.list_for_application.return_value = [_action()]
            MockFit.return_value.get_latest_for_job.return_value = SimpleNamespace(
                id="fit-1", overall_match_score=78
            )
            resp = client.get("/api/app/applications/app-1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["events"]) == 1
        assert len(body["actions"]) == 1
        assert body["events"][0]["event_type"] == "status_changed"
        assert body["fit_score"] == 78
        assert body["fit_report_id"] == "fit-1"

    def test_detail_foreign_application_returns_404(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp:
            MockApp.return_value.get.return_value = None  # repo scopes by ws → miss
            resp = client.get("/api/app/applications/does-not-exist")
        assert resp.status_code == 404

    def test_summary_counts(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockApp.return_value.count_by_status.return_value = {
                "planned": 2, "applied": 3, "rejected": 1
            }
            MockApp.return_value.list_for_workspace.return_value = [object(), object()]
            MockAct.return_value.count_due.return_value = 4
            resp = client.get("/api/app/applications/summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["planned"] == 2
        assert body["active"] == 3  # applied is active; rejected is closed
        assert body["today_due"] == 4
        assert body["needs_action"] == 2


# --- transition -------------------------------------------------------------


class TestTransition:
    def test_transition_ok(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.JobRepository") as MockJob:
            MockApp.return_value.get.return_value = _app(status="planned")
            MockApp.return_value.transition_status.return_value = _app(status="applied")
            MockJob.return_value.get.return_value = _job()
            resp = client.post(
                "/api/app/applications/app-1/transition", json={"status": "applied"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "applied"

    def test_transition_illegal_returns_400(self, make_client):
        from packages.domain.applications.transitions import InvalidTransition

        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp:
            MockApp.return_value.get.return_value = _app(status="interviewing")
            MockApp.return_value.transition_status.side_effect = InvalidTransition("nope")
            resp = client.post(
                "/api/app/applications/app-1/transition", json={"status": "planned"}
            )
        assert resp.status_code == 400

    def test_transition_unknown_status_returns_422(self, make_client):
        client = make_client()
        resp = client.post(
            "/api/app/applications/app-1/transition", json={"status": "bogus"}
        )
        assert resp.status_code == 422  # Pydantic Literal rejection, no handler reached


# --- actions ----------------------------------------------------------------


class TestActions:
    def test_create_action(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.create.return_value = _action(type="global", application_id=None)
            resp = client.post(
                "/api/app/actions", json={"type": "global", "title": "run discovery"}
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["type"] == "global"

    def test_create_action_forwards_est_minutes(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.create.return_value = _action(
                type="custom", application_id=None, est_minutes=30
            )
            resp = client.post(
                "/api/app/actions",
                json={"type": "custom", "title": "draft outreach", "est_minutes": 30},
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["est_minutes"] == 30
        _, kwargs = MockAct.return_value.create.call_args
        assert kwargs["est_minutes"] == 30

    def test_create_action_without_est_minutes_forwards_none(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.create.return_value = _action(
                type="custom", application_id=None, est_minutes=None
            )
            resp = client.post("/api/app/actions", json={"type": "custom", "title": "no est"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["est_minutes"] is None
        _, kwargs = MockAct.return_value.create.call_args
        assert kwargs["est_minutes"] is None

    def test_list_actions_defaults_to_now(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.list_due.return_value = [_action()]
            resp = client.get("/api/app/actions")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["est_minutes"] == 15

    def test_patch_action_complete(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.get.return_value = _action()
            MockAct.return_value.complete.return_value = _action(
                status="done", completed_at=_NOW
            )
            resp = client.patch("/api/app/actions/act-1", json={"op": "complete"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "done"

    def test_patch_action_foreign_returns_404(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.get.return_value = None
            resp = client.patch("/api/app/actions/nope", json={"op": "dismiss"})
        assert resp.status_code == 404


# --- planner settings + parity ----------------------------------------------


def test_funnel_endpoint(make_client):
    client = make_client()
    with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
         patch("apps.api.routes.applications.ApplicationEventRepository") as MockEv:
        MockApp.return_value.list_for_workspace.return_value = [_app(status="applied", applied_at=_NOW)]
        MockEv.return_value.list_for_application.return_value = []
        resp = client.get("/api/app/applications/funnel")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [s["key"] for s in body["stages"]] == ["planned", "applied", "in_review", "interviewing", "onsite", "offer"]
    assert "onsite_low" in [a["kind"] for a in body["alerts"]]  # 0 onsites < target


def test_planner_stats_endpoint(make_client):
    client = make_client()
    with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
         patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
        MockApp.return_value.count_applied_in_range.return_value = 3
        MockAct.return_value.count_completed_by_type_in_range.side_effect = [2, 5]  # networking, follow_up
        resp = client.get("/api/app/planner-stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] == 3 and body["outreach"] == 2 and body["follow_ups"] == 5
    assert body["weekly_target"]["apply"] == 10 and "week_start" in body


def test_planner_stats_invalid_week_422(make_client):
    client = make_client()
    resp = client.get("/api/app/planner-stats?week=notadate")
    assert resp.status_code == 422


def test_planner_settings_returns_defaults(make_client):
    client = make_client()
    resp = client.get("/api/app/planner-settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["weekly_target"]["apply"] == 10
    assert body["ghost_days"] == 14
    assert body["rest_days"] == ["sat", "sun"]


class TestPlannerSettingsPut:
    def _client_with_ws(self, ws):
        from apps.api.dependencies.auth import get_current_workspace
        from apps.api.dependencies.db import get_db
        from apps.api.main import app

        def _mock_db():
            yield MagicMock()

        app.dependency_overrides[get_db] = _mock_db
        app.dependency_overrides[get_current_workspace] = lambda: ws
        return TestClient(app, raise_server_exceptions=False)

    def test_put_merges_over_stored_and_persists(self):
        ws = _ws()
        ws.planner_settings_json = {"ghost_days": 30, "weekly_target": {"apply": 20}}
        client = self._client_with_ws(ws)
        try:
            with patch("apps.api.routes.applications.WorkspaceRepository") as MockWs:
                resp = client.put("/api/app/planner-settings", json={"daily_cap_minutes": 120})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["daily_cap_minutes"] == 120  # patched field applied
            assert body["ghost_days"] == 30  # stored preserved (merge, not reset)
            assert body["weekly_target"]["apply"] == 20  # nested stored preserved
            assert body["follow_up_days"] == 7  # unspecified stays default
            # Persisted the validated, fully-merged blob.
            MockWs.return_value.set_planner_settings.assert_called_once()
            saved = MockWs.return_value.set_planner_settings.call_args[0][1]
            assert saved["daily_cap_minutes"] == 120 and saved["ghost_days"] == 30
        finally:
            from apps.api.main import app
            app.dependency_overrides.clear()

    def test_put_invalid_timezone_422(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.WorkspaceRepository"):
            resp = client.put("/api/app/planner-settings", json={"timezone": "Mars/Nowhere"})
        assert resp.status_code == 422

    def test_put_out_of_range_422(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.WorkspaceRepository"):
            resp = client.put("/api/app/planner-settings", json={"follow_up_days": 0})
        assert resp.status_code == 422

    def test_put_invalid_search_started_at_422(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.WorkspaceRepository"):
            resp = client.put("/api/app/planner-settings", json={"search_started_at": "nope"})
        assert resp.status_code == 422

    def test_put_valid_search_started_at_persists(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.WorkspaceRepository") as MockWs:
            resp = client.put("/api/app/planner-settings", json={"search_started_at": "2026-06-01"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["search_started_at"] == "2026-06-01"
        MockWs.return_value.set_planner_settings.assert_called_once()

    def test_put_empty_body_returns_effective_defaults(self, make_client):
        client = make_client()  # ws.planner_settings_json is None
        with patch("apps.api.routes.applications.WorkspaceRepository"):
            resp = client.put("/api/app/planner-settings", json={})
        assert resp.status_code == 200
        assert resp.json()["ghost_days"] == 14


def test_status_literal_matches_domain_state_machine():
    """ApplicationStatus (contract) must not drift from transitions.STATUSES (domain)."""
    from packages.contracts.api.applications import ApplicationStatus
    from packages.domain.applications.transitions import STATUSES

    assert set(get_args(ApplicationStatus)) == set(STATUSES)


# --- review follow-ups: race fix (#1) + coverage gaps (#2-#7) ----------------


class TestCreateMore:
    def test_create_race_converges_on_409(self, make_client):
        """Concurrent duplicate submit: pre-check misses, repo.create hits the
        unique constraint -> IntegrityError must be caught and turned into 409."""
        from sqlalchemy.exc import IntegrityError

        client = make_client()
        with patch("apps.api.routes.applications._job_in_workspace", return_value=_job()), \
             patch("apps.api.routes.applications.JobApplicationRepository") as MockRepo:
            MockRepo.return_value.get_by_job.side_effect = [None, _app(id="winner")]
            MockRepo.return_value.create.side_effect = IntegrityError("stmt", {}, Exception("dup"))
            resp = client.post("/api/app/applications", json={"job_id": "job-1"})
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["existing_application_id"] == "winner"

    def test_create_persists_lane_and_excitement(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications._job_in_workspace", return_value=_job()), \
             patch("apps.api.routes.applications.JobApplicationRepository") as MockRepo:
            MockRepo.return_value.get_by_job.return_value = None
            MockRepo.return_value.create.return_value = _app(lane="a", excitement=2)
            resp = client.post(
                "/api/app/applications", json={"job_id": "job-1", "lane": "a", "excitement": 2}
            )
        assert resp.status_code == 201, resp.text
        _, kwargs = MockRepo.return_value.create.call_args
        assert kwargs["lane"] == "a" and kwargs["excitement"] == 2

    def test_create_excitement_out_of_range_returns_422(self, make_client):
        client = make_client()
        resp = client.post("/api/app/applications", json={"job_id": "job-1", "excitement": 5})
        assert resp.status_code == 422


class TestUpdate:
    def test_update_success(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.JobRepository") as MockJob:
            MockApp.return_value.get.return_value = _app()
            MockApp.return_value.update_fields.return_value = _app(notes="updated", lane="a")
            MockJob.return_value.get.return_value = _job()
            resp = client.patch(
                "/api/app/applications/app-1", json={"notes": "updated", "lane": "a"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["notes"] == "updated"

    def test_update_foreign_profile_returns_403(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.ProfileRepository") as MockProfile:
            MockApp.return_value.get.return_value = _app()
            MockProfile.return_value.get_by_id.return_value = SimpleNamespace(
                id="prof-x", workspace_id="SOME-OTHER-WS"
            )
            resp = client.patch("/api/app/applications/app-1", json={"profile_id": "prof-x"})
        assert resp.status_code == 403

    def test_update_foreign_application_returns_404(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp:
            MockApp.return_value.get.return_value = None  # repo scopes by ws → miss
            resp = client.patch("/api/app/applications/nope", json={"notes": "x"})
        assert resp.status_code == 404


class TestActionsMore:
    def test_create_action_with_owned_application(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockApp.return_value.get.return_value = _app()
            MockAct.return_value.create.return_value = _action(
                type="follow_up", application_id="app-1"
            )
            resp = client.post(
                "/api/app/actions",
                json={"type": "follow_up", "title": "ping", "application_id": "app-1"},
            )
        assert resp.status_code == 201, resp.text

    def test_create_action_foreign_application_returns_404(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp:
            MockApp.return_value.get.return_value = None
            resp = client.post(
                "/api/app/actions",
                json={"type": "follow_up", "title": "x", "application_id": "foreign"},
            )
        assert resp.status_code == 404

    def test_patch_action_snooze(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.get.return_value = _action()
            MockAct.return_value.snooze.return_value = _action(status="pending")
            resp = client.patch(
                "/api/app/actions/act-1", json={"op": "snooze", "snooze_days": 3}
            )
        assert resp.status_code == 200, resp.text
        MockAct.return_value.snooze.assert_called_once_with("act-1", WS_ID, days=3, until=None)

    def test_patch_action_snooze_until_absolute(self, make_client):
        # Rest-until-Monday passes an absolute target so overdue actions land on Monday.
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.get.return_value = _action()
            MockAct.return_value.snooze.return_value = _action(status="pending")
            resp = client.patch(
                "/api/app/actions/act-1",
                json={"op": "snooze", "snooze_until": "2026-07-20T04:00:00+00:00"},
            )
        assert resp.status_code == 200, resp.text
        _, kwargs = MockAct.return_value.snooze.call_args
        assert kwargs["until"] is not None

    def test_patch_action_dismiss(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.get.return_value = _action()
            MockAct.return_value.dismiss.return_value = _action(status="dismissed")
            resp = client.patch("/api/app/actions/act-1", json={"op": "dismiss"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "dismissed"

    def test_snooze_days_out_of_range_returns_422(self, make_client):
        client = make_client()
        resp = client.patch("/api/app/actions/act-1", json={"op": "snooze", "snooze_days": 91})
        assert resp.status_code == 422

    @pytest.mark.parametrize("bad", [4, 481])
    def test_est_minutes_out_of_range_returns_422(self, make_client, bad):
        client = make_client()
        resp = client.post(
            "/api/app/actions", json={"type": "custom", "title": "x", "est_minutes": bad}
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("ok", [5, 480])
    def test_est_minutes_accepts_inclusive_bounds(self, make_client, ok):
        """The reject-side test alone would still pass if the range were narrowed;
        this pins both ends as inclusive."""
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.create.return_value = _action(
                type="custom", application_id=None, est_minutes=ok
            )
            resp = client.post(
                "/api/app/actions", json={"type": "custom", "title": "x", "est_minutes": ok}
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["est_minutes"] == ok

    def test_list_actions_exposes_rule_facts(self, make_client):
        """The engine's reason for a to-do reaches the client, so the row can
        explain itself instead of issuing an unexplained instruction."""
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.list_due.return_value = [
                _action(payload_json={"rule": "follow_up", "days_since_applied": 9}, snooze_count=2)
            ]
            resp = client.get("/api/app/actions")
        assert resp.status_code == 200, resp.text
        item = resp.json()["items"][0]
        assert item["payload"] == {"rule": "follow_up", "days_since_applied": 9}
        assert item["snooze_count"] == 2

    def test_payload_is_whitelisted_not_passed_through(self, make_client):
        """Allow-list, so a field added to a rule payload later cannot reach the
        client until someone lists it deliberately."""
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.list_due.return_value = [
                _action(payload_json={
                    "rule": "follow_up",
                    "days_since_applied": 9,
                    "internal_debug_note": "do not ship",
                    "candidate_email": "a@b.c",
                })
            ]
            resp = client.get("/api/app/actions")
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"][0]["payload"] == {
            "rule": "follow_up", "days_since_applied": 9,
        }

    @pytest.mark.parametrize("junk", [["a"], "oops", 5, True])
    def test_non_object_payload_degrades_instead_of_500ing(self, make_client, junk):
        """payload_json is a JSON column; nothing enforces that it holds an
        object. One malformed row must not take down the whole Today list."""
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.list_due.return_value = [_action(payload_json=junk)]
            resp = client.get("/api/app/actions")
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"][0]["payload"] is None

    def test_payload_of_only_private_keys_reads_as_none(self, make_client):
        # Nothing renderable left → None, not an empty object the UI must special-case.
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.list_due.return_value = [
                _action(payload_json={"internal_only": 1})
            ]
            resp = client.get("/api/app/actions")
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"][0]["payload"] is None

    def test_read_model_serialises_out_of_range_est_minutes(self, make_client):
        """ActionRead deliberately carries no ge/le: a legacy or engine-written row
        outside the create-time range must serialise, not 500."""
        client = make_client()
        with patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
            MockAct.return_value.list_due.return_value = [_action(est_minutes=600)]
            resp = client.get("/api/app/actions")
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"][0]["est_minutes"] == 600


def test_list_forwards_needs_action_filter(make_client):
    client = make_client()
    with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
         patch("apps.api.routes.applications.JobRepository") as MockJob, \
         patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
        MockApp.return_value.list_for_workspace.return_value = []
        MockAct.return_value.earliest_pending_action_map.return_value = {}
        resp = client.get("/api/app/applications?needs_action=true")
    assert resp.status_code == 200
    _, kwargs = MockApp.return_value.list_for_workspace.call_args
    assert kwargs["needs_action"] is True


# --- timeline note events (W0-C2) -------------------------------------------


class TestEvents:
    def test_add_note_appends_note_event(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.ApplicationEventRepository") as MockEv:
            MockApp.return_value.get.return_value = _app()
            MockEv.return_value.append.return_value = _event(
                id="ev-note", event_type="note", message="called recruiter", payload_json=None
            )
            resp = client.post(
                "/api/app/applications/app-1/events", json={"message": "called recruiter"}
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["event_type"] == "note"
        assert body["message"] == "called recruiter"
        # event_type is pinned server-side, never taken from the client body
        _, kwargs = MockEv.return_value.append.call_args
        assert kwargs["event_type"] == "note"

    def test_add_note_foreign_application_returns_404(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp:
            MockApp.return_value.get.return_value = None  # repo scopes by ws → miss
            resp = client.post(
                "/api/app/applications/foreign/events", json={"message": "x"}
            )
        assert resp.status_code == 404

    def test_add_note_empty_message_returns_422(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp:
            MockApp.return_value.get.return_value = _app()  # owned → reaches the message check
            resp = client.post("/api/app/applications/app-1/events", json={"message": ""})
        assert resp.status_code == 422

    def test_add_interview_event(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
             patch("apps.api.routes.applications.ApplicationEventRepository") as MockEv:
            MockApp.return_value.get.return_value = _app()
            MockEv.return_value.append.return_value = _event(
                id="ev-int", event_type="interview_scheduled", message=None,
                payload_json={"round_type": "onsite", "at": "2026-07-20T15:00:00+00:00"},
            )
            resp = client.post(
                "/api/app/applications/app-1/events",
                json={"event_type": "interview_scheduled", "round_type": "onsite",
                      "at": "2026-07-20T15:00:00+00:00"},
            )
        assert resp.status_code == 201, resp.text
        _, kwargs = MockEv.return_value.append.call_args
        assert kwargs["event_type"] == "interview_scheduled"
        assert kwargs["payload_json"]["round_type"] == "onsite"

    def test_add_interview_missing_fields_returns_422(self, make_client):
        client = make_client()
        with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp:
            MockApp.return_value.get.return_value = _app()
            resp = client.post(
                "/api/app/applications/app-1/events", json={"event_type": "interview_scheduled"}
            )
        assert resp.status_code == 422

    def test_add_event_rejects_forged_event_type(self, make_client):
        # A forged status_changed is rejected by the Literal enum before the handler.
        client = make_client()
        resp = client.post(
            "/api/app/applications/app-1/events",
            json={"event_type": "status_changed", "message": "x"},
        )
        assert resp.status_code == 422


def test_summary_exposes_by_status_for_per_pill_counts(make_client):
    """Per-pill counts (W0-C2) read summary.by_status — assert it is surfaced."""
    client = make_client()
    with patch("apps.api.routes.applications.JobApplicationRepository") as MockApp, \
         patch("apps.api.routes.applications.ApplicationActionRepository") as MockAct:
        MockApp.return_value.count_by_status.return_value = {
            "planned": 2, "applied": 3, "interviewing": 1
        }
        MockApp.return_value.list_for_workspace.return_value = []
        MockAct.return_value.count_due.return_value = 0
        resp = client.get("/api/app/applications/summary")
    assert resp.status_code == 200, resp.text
    assert resp.json()["by_status"] == {"planned": 2, "applied": 3, "interviewing": 1}


def test_planner_settings_merges_stored_overrides():
    """Stored planner_settings_json overrides defaults; nested + unspecified keys behave."""
    from apps.api.dependencies.auth import get_current_workspace
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _mock_db():
        yield MagicMock()

    ws = SimpleNamespace(
        id=WS_ID, name="t", tier="beta", created_at=_NOW, updated_at=_NOW,
        planner_settings_json={"ghost_days": 30, "weekly_target": {"apply": 20}},
    )
    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_workspace] = lambda: ws
    try:
        resp = TestClient(app, raise_server_exceptions=False).get("/api/app/planner-settings")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ghost_days"] == 30  # top-level override
        assert body["weekly_target"]["apply"] == 20  # nested override
        assert body["weekly_target"]["outreach"] == 5  # nested unspecified -> default
        assert body["follow_up_days"] == 7  # top-level unspecified -> default
    finally:
        app.dependency_overrides.clear()
