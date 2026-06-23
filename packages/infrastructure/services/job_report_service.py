"""
JobReportService — orchestrates Job Intelligence Report generation.

Entry point: create_job_report()

Flow:
  1. Load job record (from DB by job_id, or from job_snapshot smoke path)
  2. Check cache (job_id + jd_hash + prompt_version + research_bundle_hash)
  3. Load taxonomy
  4. Load research notes from artifact (optional)
  5. Call analyze_role() — Layer 1 narrative + Layer 2 structured
  6. Stamp research provenance onto structured report
  7. Write narrative .md + structured .json artifacts
  8. Supersede prior active report, create job_reports DB row
  9. Return {job_report_id, status, used_research}
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import Session

from packages.contracts.reports.job_report import JobReportStructured
from packages.domain.reports.cache_keys import job_report_cache_key
from packages.domain.reports.taxonomy import get_taxonomy
from packages.infrastructure.db.repositories import (
    ArtifactRepository,
    JobRepository,
    JobReportRepository,
)
from packages.infrastructure.llm.client import LLMCallError, get_llm_client
from packages.infrastructure.llm.reports.role_analyzer import PROMPT_VERSION, analyze_role

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")
ANALYSIS_VERSION = "1.0"


def create_job_report(
    *,
    session: Session,
    run_id: str,
    task_id: str,
    workspace_id: str,
    job_id: Optional[str] = None,
    job_snapshot: Optional[dict[str, Any]] = None,
    use_research: bool = True,
    research_artifact_id: Optional[str] = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Generate (or return cached) a global Job Intelligence Report.

    Either job_id (loads from DB) or job_snapshot (smoke/test path) must be provided.

    Returns:
        {
          "job_report_id": str,
          "status": "created" | "cache_hit",
          "used_research": bool,
          "narrative_artifact_id": str,
          "structured_artifact_id": str,
        }
    """
    if not job_id and not job_snapshot:
        raise ValueError("Either job_id or job_snapshot must be provided.")

    job_repo = JobRepository(session)
    report_repo = JobReportRepository(session)
    artifact_repo = ArtifactRepository(session)

    # 1. Load job record
    if job_id:
        job_record = _job_orm_to_dict(job_repo.get_reportable(job_id))
    else:
        # Smoke path: job_snapshot dict must have title, company, jd_text at minimum
        job_record = job_snapshot  # type: ignore[assignment]
        job_id = job_record.get("id") or job_record.get("job_id") or "smoke_" + uuid.uuid4().hex[:8]

    jd_text = job_record.get("jd_text") or job_record.get("description") or ""
    if not jd_text.strip():
        raise ValueError(f"No jd_text available for job {job_id!r}")

    # 2. Compute cache key components
    jd_hash = hashlib.md5(jd_text.encode("utf-8")).hexdigest()[:16]

    # 3. Resolve research notes
    research_notes = ""
    research_bundle_hash = "none"
    research_artifact_meta: dict = {}
    used_research = False

    if use_research and research_artifact_id:
        research_notes, research_bundle_hash, research_artifact_meta = _load_research_notes(
            artifact_repo, research_artifact_id
        )
        used_research = bool(research_notes)

    # 4. Cache check
    if not force_refresh:
        cached = report_repo.get_active(
            job_id=job_id,
            jd_hash=jd_hash,
            prompt_version=PROMPT_VERSION,
            research_bundle_hash=research_bundle_hash,
        )
        if cached:
            logger.info("job_report: cache hit for job_id=%s report_id=%s", job_id, cached.id)
            return {
                "job_report_id": cached.id,
                "status": "cache_hit",
                "used_research": cached.used_research,
                "narrative_artifact_id": cached.narrative_artifact_id,
                "structured_artifact_id": cached.structured_artifact_id,
            }

    # 5. Load taxonomy + LLM client
    taxonomy = get_taxonomy()
    llm = get_llm_client()

    # 6. Run analysis
    logger.info("job_report: running analysis for job_id=%s", job_id)
    try:
        report_md, structured, prompt_version = analyze_role(
            jd_text=jd_text,
            job_record=job_record,
            taxonomy=taxonomy,
            llm_client=llm,
            research_notes=research_notes,
        )
    except (LLMCallError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"Role analysis failed for job {job_id}: {exc}") from exc

    # 7. Stamp research provenance
    structured.used_research = used_research
    structured.research_bundle_hash = research_bundle_hash
    if used_research:
        # Read validation_status / source_count from artifact metadata written by research pipeline.
        # If the metadata does not carry these fields yet, use safe fallbacks:
        # "partial" (not "passed" — we cannot confirm validity from text alone) and 0.
        structured.research_validation_status = research_artifact_meta.get(
            "validation_status", "partial"
        )
        structured.research_source_count = int(
            research_artifact_meta.get("source_count", 0)
        )

    # 8. Write artifacts
    job_report_id = "rpt_" + uuid.uuid4().hex[:8]
    artifact_dir = Path(_ARTIFACTS_DIR) / run_id / task_id / job_report_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    narrative_path = artifact_dir / "job_report.md"
    structured_path = artifact_dir / "job_report.json"

    narrative_path.write_text(report_md, encoding="utf-8")
    structured_path.write_text(
        json.dumps(structured.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    narrative_artifact = artifact_repo.create(
        run_id=run_id,
        task_id=task_id,
        artifact_type="job_report_narrative",
        storage_uri=str(narrative_path),
        metadata_json={"job_id": job_id, "char_count": len(report_md)},
    )
    structured_artifact = artifact_repo.create(
        run_id=run_id,
        task_id=task_id,
        artifact_type="job_report_structured",
        storage_uri=str(structured_path),
        metadata_json={"job_id": job_id, "prompt_version": prompt_version},
    )

    # 9. Supersede prior + create DB row
    report_repo.supersede_prior(job_id)
    job_report_row = report_repo.create(
        job_id=job_id,
        jd_hash=jd_hash,
        prompt_version=prompt_version,
        analysis_version=ANALYSIS_VERSION,
        used_research=used_research,
        research_artifact_id=research_artifact_id,
        research_bundle_hash=research_bundle_hash,
        narrative_artifact_id=narrative_artifact.id,
        structured_artifact_id=structured_artifact.id,
        structured_json=structured.model_dump(),
        summary_json={
            "primary_workstream": structured.primary_workstream,
            "analyst_notes": structured.analyst_notes[:200] if structured.analyst_notes else "",
        },
    )

    logger.info("job_report: created report_id=%s for job_id=%s", job_report_row.id, job_id)
    return {
        "job_report_id": job_report_row.id,
        "status": "created",
        "used_research": used_research,
        "narrative_artifact_id": narrative_artifact.id,
        "structured_artifact_id": structured_artifact.id,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _job_orm_to_dict(job) -> dict[str, Any]:
    """Convert Job ORM instance to a dict suitable for analyze_role()."""
    return {
        "id": job.id,
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location or "",
        "source_url": job.source_url,
        "jd_text": job.jd_text,
        "status": job.status,
    }


def _load_research_notes(
    artifact_repo: ArtifactRepository,
    research_artifact_id: str,
) -> tuple[str, str, dict]:
    """
    Load research notes text and compute bundle hash.
    Also returns artifact.metadata_json for provenance stamping.
    Returns ("", "none", {}) on failure.
    """
    try:
        artifact = artifact_repo.get(research_artifact_id)
        if artifact is None:
            logger.warning("Research artifact not found: %s", research_artifact_id)
            return "", "none", {}
        path = Path(artifact.storage_uri)
        if not path.exists():
            logger.warning("Research artifact file missing: %s", path)
            return "", "none", {}
        text = path.read_text(encoding="utf-8").strip()
        bundle_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
        artifact_meta = artifact.metadata_json or {}
        return text, bundle_hash, artifact_meta
    except Exception as exc:
        logger.warning("Failed to load research notes from %s: %s", research_artifact_id, exc)
        return "", "none", {}
