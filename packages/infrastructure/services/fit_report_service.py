"""
FitReportService — orchestrates workspace-private Candidate Fit Report generation.

Entry point: create_fit_report()

Flow:
  1. Load job record from DB
  2. Load active Job Intelligence Report — raises MISSING_JOB_REPORT if none found
  3. Load structured job report JSON from artifact
  4. Resolve candidate profile (from profile_snapshot; full profile_id lookup is future work)
  5. Compute profile_hash, check cache
  6. Call generate_fit_report()
  7. Write narrative .md + structured .json artifacts
  8. Supersede prior + create fit_reports DB row
  9. Return result dict
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path


def _compute_file_sha256(path: Path) -> str | None:
    """Return sha256:<hex> for the file, or None if unreadable."""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return f"sha256:{digest}"
    except OSError:
        return None
from typing import Any, Optional

from sqlalchemy.orm import Session

from packages.contracts.profile.candidate import CandidateProfile
from packages.contracts.reports.fit_report import FitReportStructured
from packages.domain.reports.cache_keys import fit_report_cache_key
from packages.infrastructure.db.repositories import (
    ArtifactRepository,
    FitReportRepository,
    JobReportRepository,
)
from packages.infrastructure.llm.client import LLMCallError, get_llm_client
from packages.infrastructure.llm.reports.fit_reporter import FIT_PROMPT_VERSION, generate_fit_report

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")


def create_fit_report(
    *,
    session: Session,
    run_id: str,
    task_id: str,
    workspace_id: str,
    job_id: str,
    candidate_profile_id: Optional[str] = None,
    profile_snapshot: Optional[dict[str, Any]] = None,
    job_report_id: Optional[str] = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Generate (or return cached) a workspace-scoped Candidate Fit Report.

    Requires a candidate profile (profile_snapshot for MVP; profile_id lookup is future work).
    Raises ValueError with code MISSING_JOB_REPORT if no active job report exists.

    Returns:
        {
          "fit_report_id": str,
          "status": "created" | "cache_hit",
          "overall_match_score": int,
          "structured_artifact_id": str,
          "narrative_artifact_id": str,
        }
    """
    if not profile_snapshot:
        raise ValueError(
            "profile_snapshot is required for MVP. "
            "Passing only candidate_profile_id without profile_snapshot is not supported yet — "
            "the system cannot resolve the profile from the database."
        )

    try:
        validated_profile = CandidateProfile.model_validate(profile_snapshot)
    except Exception as exc:
        raise ValueError(f"Invalid profile_snapshot: {exc}") from exc
    profile_snapshot = validated_profile.model_dump(exclude_none=False)

    report_repo = JobReportRepository(session)
    fit_repo = FitReportRepository(session)
    artifact_repo = ArtifactRepository(session)

    # 2. Load active Job Intelligence Report
    if job_report_id:
        active_report = report_repo.get(job_report_id)
        if active_report is None or active_report.status != "active":
            raise ValueError(
                f"MISSING_JOB_REPORT: Job report {job_report_id!r} not found or not active. "
                "Generate a Job Intelligence Report first."
            )
    else:
        active_report = report_repo.get_latest_active(job_id)
        if active_report is None:
            raise ValueError(
                f"MISSING_JOB_REPORT: No active Job Intelligence Report found for job {job_id!r}. "
                "Run job_report first before generating a fit report."
            )

    job_report_id = active_report.id

    # 3. Load structured job report from artifact or inline JSON
    structured_job_report: dict[str, Any] = {}
    if active_report.structured_json:
        structured_job_report = active_report.structured_json
    elif active_report.structured_artifact_id:
        art = artifact_repo.get(active_report.structured_artifact_id)
        if art:
            sp = Path(art.storage_uri)
            if sp.exists():
                try:
                    structured_job_report = json.loads(sp.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning("Failed to load structured job report from %s: %s", sp, exc)

    # 4. Resolve candidate profile
    candidate_profile: dict[str, Any] = profile_snapshot or {}
    effective_profile_id = candidate_profile_id or candidate_profile.get("id") or "profile_" + uuid.uuid4().hex[:8]

    # 5. Compute profile_hash
    profile_hash = hashlib.md5(
        json.dumps(candidate_profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]

    # 6. Cache check
    if not force_refresh:
        cached = fit_repo.get_active(
            workspace_id=workspace_id,
            job_id=job_id,
            job_report_id=job_report_id,
            candidate_profile_id=effective_profile_id,
            profile_hash=profile_hash,
            prompt_version=FIT_PROMPT_VERSION,
        )
        if cached:
            logger.info("fit_report: cache hit fit_report_id=%s", cached.id)
            return {
                "fit_report_id": cached.id,
                "status": "cache_hit",
                "overall_match_score": cached.overall_match_score,
                "structured_artifact_id": cached.structured_artifact_id,
                "narrative_artifact_id": cached.narrative_artifact_id,
            }

    # 7. Load job record for prompt context
    job_record: dict[str, Any] = {}
    from packages.infrastructure.db.repositories import JobRepository  # noqa: PLC0415
    job_orm = JobRepository(session).get(job_id)
    if job_orm:
        job_record = {
            "id": job_orm.id,
            "job_id": job_orm.id,
            "title": job_orm.title,
            "company": job_orm.company,
            "location": job_orm.location or "",
            "source_url": job_orm.source_url,
            "primary_workstream": structured_job_report.get("primary_workstream", ""),
        }

    # 8. Generate fit report
    fit_report_id = "fit_" + uuid.uuid4().hex[:8]
    llm = get_llm_client()

    logger.info("fit_report: generating fit_report_id=%s job_id=%s", fit_report_id, job_id)
    try:
        structured_fit, narrative_md = generate_fit_report(
            job_record=job_record,
            structured_job_report=structured_job_report,
            candidate_profile=candidate_profile,
            fit_report_id=fit_report_id,
            job_report_id=job_report_id,
            workspace_id=workspace_id,
            profile_id=effective_profile_id,
            llm_client=llm,
        )
    except (LLMCallError, RuntimeError) as exc:
        raise RuntimeError(f"Fit report generation failed: {exc}") from exc

    # 9. Write artifacts
    artifact_dir = Path(_ARTIFACTS_DIR) / run_id / task_id / fit_report_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    narrative_path = artifact_dir / "fit_report.md"
    structured_path = artifact_dir / "fit_report.json"

    narrative_path.write_text(narrative_md, encoding="utf-8")
    structured_path.write_text(
        json.dumps(structured_fit.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    narrative_artifact = artifact_repo.create(
        run_id=run_id,
        task_id=task_id,
        artifact_type="fit_report_narrative",
        storage_uri=str(narrative_path),
        content_hash=_compute_file_sha256(narrative_path),
        metadata_json={"job_id": job_id, "fit_report_id": fit_report_id},
    )
    structured_artifact = artifact_repo.create(
        run_id=run_id,
        task_id=task_id,
        artifact_type="fit_report_structured",
        storage_uri=str(structured_path),
        content_hash=_compute_file_sha256(structured_path),
        metadata_json={
            "job_id": job_id,
            "job_report_id": job_report_id,
            "overall_match_score": structured_fit.overall_match_score,
        },
    )

    # 10. Supersede prior + create DB row
    fit_repo.supersede_prior(
        workspace_id=workspace_id,
        job_id=job_id,
        candidate_profile_id=effective_profile_id if candidate_profile_id else None,
        profile_hash=profile_hash,
    )
    fit_row = fit_repo.create(
        workspace_id=workspace_id,
        job_id=job_id,
        job_report_id=job_report_id,
        candidate_profile_id=effective_profile_id,
        profile_hash=profile_hash,
        prompt_version=FIT_PROMPT_VERSION,
        overall_match_score=structured_fit.overall_match_score,
        structured_artifact_id=structured_artifact.id,
        narrative_artifact_id=narrative_artifact.id,
        structured_json=structured_fit.model_dump(),
        summary_json={
            "overall_match_score": structured_fit.overall_match_score,
            "match_summary": structured_fit.match_summary[:200] if structured_fit.match_summary else "",
            "recommended_next_action": structured_fit.recommended_next_action,
        },
    )

    logger.info("fit_report: created fit_report_id=%s score=%d", fit_row.id, fit_row.overall_match_score)
    return {
        "fit_report_id": fit_row.id,
        "status": "created",
        "overall_match_score": fit_row.overall_match_score,
        "structured_artifact_id": structured_artifact.id,
        "narrative_artifact_id": narrative_artifact.id,
    }
