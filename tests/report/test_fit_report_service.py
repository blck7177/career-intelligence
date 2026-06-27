"""
Unit tests for fit_report_service.create_fit_report().

Strategy: real SQLite ORM for DB, patched generate_fit_report for LLM.
All artifact writes go to pytest tmp_path.

Cases:
  1. fit_report rejects candidate_profile_id-only input (no profile_snapshot)
  2. fit_report raises MISSING_JOB_REPORT when no active job_report exists
  3. fit_report cache is isolated by workspace_id (different ws → cache miss)
  4. fit_report DB row stores effective_profile_id and structured_json.job_id
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session

from packages.contracts.reports.fit_report import FitReportStructured, ResumeRewriteStrategy
from packages.infrastructure.services.fit_report_service import create_fit_report
from packages.infrastructure.db.models import FitReport, Workspace

from tests.report.conftest import SAMPLE_PROFILE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_structured_fit(job_id: str = "job_seed", score: int = 72) -> FitReportStructured:
    return FitReportStructured(
        overall_match_score=score,
        match_summary="Good match with addressable gaps.",
        strong_matches=[],
        partial_matches=[],
        gaps=[],
        risk_flags=[],
        interview_talking_points=["Discuss VaR rebuild project."],
        resume_rewrite_strategy=ResumeRewriteStrategy(
            positioning="Frame as quantitative risk specialist.",
        ),
        recommended_next_action="apply now",
    )


# ---------------------------------------------------------------------------
# Test 1: rejects missing profile_snapshot
# ---------------------------------------------------------------------------


class TestFitReportRejectsMissingProfile:
    def test_raises_when_profile_snapshot_is_none(self, db_session: Session):
        with pytest.raises(ValueError, match="profile_snapshot is required"):
            create_fit_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id="ws_seed",
                job_id="job_seed",
                profile_snapshot=None,
            )

    def test_raises_when_only_candidate_profile_id_provided(self, db_session: Session):
        """candidate_profile_id alone (no profile_snapshot) is not supported in MVP."""
        with pytest.raises(ValueError, match="profile_snapshot is required"):
            create_fit_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id="ws_seed",
                job_id="job_seed",
                candidate_profile_id="cand_abc",
                profile_snapshot=None,
            )


# ---------------------------------------------------------------------------
# Test 2: MISSING_JOB_REPORT when no active report exists
# ---------------------------------------------------------------------------


class TestFitReportRequiresJobReport:
    def test_raises_when_no_active_job_report(self, db_session: Session):
        """job_id with no corresponding active job_report → MISSING_JOB_REPORT."""
        with pytest.raises(ValueError, match="MISSING_JOB_REPORT"):
            create_fit_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id="ws_seed",
                job_id="job_with_no_report",
                profile_snapshot=SAMPLE_PROFILE,
            )

    def test_raises_for_explicit_job_report_id_not_active(self, db_session: Session, seeded_db):
        """Passing a job_report_id that is not active → MISSING_JOB_REPORT."""
        # seeded_db has rpt_seed (active). Use a non-existent ID.
        with pytest.raises(ValueError, match="MISSING_JOB_REPORT"):
            create_fit_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id=seeded_db["workspace_id"],
                job_id=seeded_db["job_id"],
                job_report_id="rpt_does_not_exist",
                profile_snapshot=SAMPLE_PROFILE,
            )


# ---------------------------------------------------------------------------
# Test 3: cache is isolated by workspace_id
# ---------------------------------------------------------------------------


class TestFitReportCacheIsolation:
    def test_different_workspace_is_cache_miss(self, db_session: Session, seeded_db, tmp_path):
        """
        Generate a fit_report for ws_a, then request for ws_b with same profile.
        ws_b must not get a cache hit — it should trigger a new LLM call.
        """
        # Add a second workspace so FitReport FK is satisfied.
        db_session.add(Workspace(id="ws_b", name="Workspace B"))
        db_session.flush()

        structured = _make_structured_fit()
        narrative = "# Fit Report\n\nGood match."

        with patch(
            "packages.infrastructure.services.fit_report_service.generate_fit_report",
            return_value=(structured, narrative),
        ) as mock_gen, patch(
            "packages.infrastructure.services.fit_report_service._ARTIFACTS_DIR",
            str(tmp_path),
        ):
            # First call: workspace A
            result_a = create_fit_report(
                session=db_session,
                run_id="run_a",
                task_id="task_a",
                workspace_id=seeded_db["workspace_id"],  # "ws_seed"
                job_id=seeded_db["job_id"],
                profile_snapshot=SAMPLE_PROFILE,
            )
            assert result_a["status"] == "created"
            assert mock_gen.call_count == 1

            # Second call: same profile, different workspace → cache miss → LLM called again
            result_b = create_fit_report(
                session=db_session,
                run_id="run_b",
                task_id="task_b",
                workspace_id="ws_b",
                job_id=seeded_db["job_id"],
                profile_snapshot=SAMPLE_PROFILE,
            )
            assert result_b["status"] == "created"
            assert mock_gen.call_count == 2, "Different workspace must not share cache"

    def test_same_workspace_same_profile_is_cache_hit(self, db_session: Session, seeded_db, tmp_path):
        """Same workspace + same profile → second call returns cache_hit, no LLM call."""
        structured = _make_structured_fit()

        with patch(
            "packages.infrastructure.services.fit_report_service.generate_fit_report",
            return_value=(structured, "# narrative"),
        ) as mock_gen, patch(
            "packages.infrastructure.services.fit_report_service._ARTIFACTS_DIR",
            str(tmp_path),
        ):
            create_fit_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id=seeded_db["workspace_id"],
                job_id=seeded_db["job_id"],
                profile_snapshot=SAMPLE_PROFILE,
            )
            result2 = create_fit_report(
                session=db_session,
                run_id="run_2",
                task_id="task_2",
                workspace_id=seeded_db["workspace_id"],
                job_id=seeded_db["job_id"],
                profile_snapshot=SAMPLE_PROFILE,
            )

        assert result2["status"] == "cache_hit"
        assert mock_gen.call_count == 1


# ---------------------------------------------------------------------------
# Test 4: DB row uses effective_profile_id and structured_json stores job_id
# ---------------------------------------------------------------------------


class TestFitReportDbRow:
    def test_db_row_stores_effective_profile_id(self, db_session: Session, seeded_db, tmp_path):
        """When candidate_profile_id is given, DB row must store it as candidate_profile_id."""
        structured = _make_structured_fit()

        with patch(
            "packages.infrastructure.services.fit_report_service.generate_fit_report",
            return_value=(structured, "# narrative"),
        ), patch(
            "packages.infrastructure.services.fit_report_service._ARTIFACTS_DIR",
            str(tmp_path),
        ):
            result = create_fit_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id=seeded_db["workspace_id"],
                job_id=seeded_db["job_id"],
                candidate_profile_id="cand_explicit_id",
                profile_snapshot=SAMPLE_PROFILE,
            )

        row = db_session.get(FitReport, result["fit_report_id"])
        assert row is not None
        assert row.candidate_profile_id == "cand_explicit_id"

    def test_db_row_auto_generates_profile_id_when_not_provided(
        self, db_session: Session, seeded_db, tmp_path
    ):
        """When profile_snapshot has no id and no candidate_profile_id, service generates profile_<hex>."""
        structured = _make_structured_fit()
        # Strip the stable id so the service must auto-generate one.
        anonymous_profile = {k: v for k, v in SAMPLE_PROFILE.items() if k != "id"}

        with patch(
            "packages.infrastructure.services.fit_report_service.generate_fit_report",
            return_value=(structured, "# narrative"),
        ), patch(
            "packages.infrastructure.services.fit_report_service._ARTIFACTS_DIR",
            str(tmp_path),
        ):
            result = create_fit_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id=seeded_db["workspace_id"],
                job_id=seeded_db["job_id"],
                profile_snapshot=anonymous_profile,
            )

        row = db_session.get(FitReport, result["fit_report_id"])
        assert row is not None
        assert row.candidate_profile_id is not None
        assert row.candidate_profile_id.startswith("profile_")

    def test_structured_artifact_metadata_contains_job_id(
        self, db_session: Session, seeded_db, tmp_path
    ):
        """Structured artifact metadata_json must include job_id for traceability."""
        from packages.infrastructure.db.models import Artifact

        structured = _make_structured_fit()

        with patch(
            "packages.infrastructure.services.fit_report_service.generate_fit_report",
            return_value=(structured, "# narrative"),
        ), patch(
            "packages.infrastructure.services.fit_report_service._ARTIFACTS_DIR",
            str(tmp_path),
        ):
            result = create_fit_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id=seeded_db["workspace_id"],
                job_id=seeded_db["job_id"],
                profile_snapshot=SAMPLE_PROFILE,
            )

        structured_artifact = db_session.get(Artifact, result["structured_artifact_id"])
        assert structured_artifact is not None
        assert structured_artifact.metadata_json is not None
        assert structured_artifact.metadata_json.get("job_id") == seeded_db["job_id"]
