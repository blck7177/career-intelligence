"""
Unit tests for job_report_service.create_job_report().

Cases:
  1. Requires a job with status='reportable'; non-reportable or missing job raises ValueError.
  2. Smoke path (job_snapshot) succeeds without a DB job row.
  3. Cache hit: same jd_hash + prompt_version returns existing report without LLM call.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from sqlalchemy.orm import Session

from packages.contracts.reports.job_report import JobReportStructured
from packages.infrastructure.services.job_report_service import create_job_report
from packages.infrastructure.db.models import Job, JobReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_JD = "We need a quantitative analyst with VaR modelling experience."

SAMPLE_JOB_SNAPSHOT = {
    "title": "Quantitative Risk Analyst",
    "company": "Example Capital",
    "location": "New York",
    "jd_text": SAMPLE_JD,
}


def _make_structured_report() -> JobReportStructured:
    return JobReportStructured(
        primary_workstream="market_risk",
        analyst_notes="Strong quant role.",
    )


# ---------------------------------------------------------------------------
# Test 1: requires reportable job
# ---------------------------------------------------------------------------


class TestJobReportRequiresReportableJob:
    def test_raises_for_missing_job(self, db_session: Session):
        """job_id that does not exist → ValueError from get_or_raise."""
        with pytest.raises(ValueError):
            create_job_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id="ws_seed",
                job_id="job_does_not_exist",
            )

    def test_raises_for_discovered_status_job(self, db_session: Session):
        """Job with status='discovered' is not reportable → ValueError."""
        job = Job(
            id="job_disc",
            canonical_url="https://example.com/job/disc",
            source_url="https://example.com/job/disc",
            source_type="ats",
            title="Analyst",
            company="Corp",
            jd_text=SAMPLE_JD,
            jd_hash="abc123",
            status="discovered",
        )
        db_session.add(job)
        db_session.flush()

        with pytest.raises(ValueError, match="not reportable"):
            create_job_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id="ws_seed",
                job_id="job_disc",
            )


# ---------------------------------------------------------------------------
# Test 2: smoke path (job_snapshot bypasses DB job lookup)
# ---------------------------------------------------------------------------


class TestJobReportSmokeSnapshot:
    def test_smoke_path_creates_report(self, db_session: Session, seeded_db, tmp_path):
        """
        When job_snapshot is provided instead of job_id, the service bypasses
        the DB job lookup and generates a report directly.
        """
        structured = _make_structured_report()

        with patch(
            "packages.infrastructure.services.job_report_service.analyze_role",
            return_value=("# Job Report\n\nNarrative.", structured, "0.2.0"),
        ), patch(
            "packages.infrastructure.services.job_report_service.get_taxonomy",
            return_value={},
        ), patch(
            "packages.infrastructure.services.job_report_service.get_llm_client",
            return_value=None,
        ), patch(
            "packages.infrastructure.services.job_report_service._ARTIFACTS_DIR",
            str(tmp_path),
        ):
            result = create_job_report(
                session=db_session,
                run_id="run_smoke",
                task_id="task_smoke",
                workspace_id="ws_seed",
                job_snapshot=SAMPLE_JOB_SNAPSHOT,
                use_research=False,
            )

        assert result["status"] == "created"
        assert result["job_report_id"]  # DB-assigned UUID, non-empty
        assert result["used_research"] is False

    def test_smoke_path_requires_jd_text(self, db_session: Session):
        """job_snapshot without jd_text → ValueError before LLM is called."""
        with pytest.raises(ValueError, match="No jd_text"):
            create_job_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id="ws_seed",
                job_snapshot={"title": "Analyst", "company": "Corp"},
            )


# ---------------------------------------------------------------------------
# Test 3: cache hit (same jd_hash + prompt_version → no LLM call)
# ---------------------------------------------------------------------------


class TestJobReportCacheHit:
    def test_returns_cached_report_without_llm(self, db_session: Session, seeded_db, tmp_path):
        """
        Insert a job_report row matching the cache key. create_job_report should
        return it immediately without calling analyze_role.
        seeded_db already has job_seed (reportable) and rpt_seed (active, prompt=0.2.0).
        """
        from packages.infrastructure.llm.reports.role_analyzer import PROMPT_VERSION

        # The seeded job_report's jd_hash matches the seeded job's jd_hash.
        # create_job_report with job_id=job_seed + force_refresh=False → cache hit.
        # use_research=False so research_bundle_hash stays "none" (matches seed).
        with patch(
            "packages.infrastructure.services.job_report_service.analyze_role"
        ) as mock_analyze, patch(
            "packages.infrastructure.services.job_report_service.get_taxonomy",
            return_value={},
        ), patch(
            "packages.infrastructure.services.job_report_service.get_llm_client",
            return_value=None,
        ), patch(
            "packages.infrastructure.services.job_report_service._ARTIFACTS_DIR",
            str(tmp_path),
        ):
            result = create_job_report(
                session=db_session,
                run_id="run_1",
                task_id="task_1",
                workspace_id=seeded_db["workspace_id"],
                job_id=seeded_db["job_id"],
                use_research=False,
                force_refresh=False,
            )

        assert result["status"] == "cache_hit"
        assert result["job_report_id"] == seeded_db["job_report_id"]
        mock_analyze.assert_not_called()
