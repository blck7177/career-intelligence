"""
JobIngestService — the single deterministic job-ingest pipeline behind both the
URL importer and the paste importer (one machine, two feed chutes).

Entry points:
  ingest_from_url(db, workspace, url)                       — fetch + extract a JD from a URL
  ingest_from_paste(db, workspace, company, title, jd_text) — a pasted JD, no URL

Both build a run/task (run_type="manual_import"), bind the LLM cost context, run
the shared extract/create path, and return a JobIngestResult (raw Job ORM row +
created + jd_fetched flags; the API route builds JobImportResponse via _job_read).

The URL path preserves import_job's original semantics verbatim (3-level fetch,
DOA/dead-url recording, cross-workspace dedup → 409). The paste path synthesizes
a manual://<ws>/<md5(jd)> canonical url so the row dedups + references like any
other job, but — being a non-http scheme — never re-enters the fetch /
reconciliation / dead-url machinery (those all guard on http(s) already; see the
W1 http-assumption audit note in apps/api/routes/jobs.py).

Note: raises fastapi.HTTPException for the 4 caller-facing error cases (bad
scheme / LinkedIn / cross-workspace 409 / DOA 404 / paste-JD rejected 422),
lifted verbatim from the original route handler.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from packages.infrastructure.db.models import Job, Workspace
from packages.infrastructure.db.repositories import (
    DeadUrlRepository,
    JobRepository,
    RunRepository,
    TaskRepository,
)

logger = logging.getLogger(__name__)

_BLOCKED_HOSTS = ("linkedin.com", "www.linkedin.com")


@dataclass
class JobIngestResult:
    """Raw ingest outcome; the route maps `.job` through _job_read into the API
    JobImportResponse (which needs route-layer helpers that can't live here)."""

    job: Job
    created: bool
    jd_fetched: bool


def ingest_from_url(db: Session, workspace: Workspace, url: str) -> JobIngestResult:
    """Import a single job by URL: fetch JD, extract fields, persist.

    Verbatim lift of the original import_job body — only the two response
    constructions become JobIngestResult (the route rebuilds JobImportResponse)."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    from urllib.parse import urlparse
    if urlparse(url).hostname in _BLOCKED_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="LinkedIn requires login to view job postings. Please use the direct employer or ATS URL instead.",
        )

    from packages.domain.agent_jobs.url_normalize import normalize_job_url
    url = normalize_job_url(url)

    job_repo = JobRepository(db)

    existing = job_repo.get_by_canonical_url(url)
    if existing:
        run = RunRepository(db).get(existing.discovered_run_id) if existing.discovered_run_id else None
        if run and run.workspace_id != workspace.id:
            raise HTTPException(status_code=409, detail="Job already exists in another workspace.")
        return JobIngestResult(
            job=existing,
            created=False,
            jd_fetched=existing.jd_text is not None,
        )

    from packages.domain.agent_jobs.ats_providers import extract_board_info
    from packages.domain.agent_jobs.source_registry import normalize_source_type
    from packages.infrastructure.jd_fetch import fetch_jd_from_url
    from packages.infrastructure.llm.client import get_llm_client
    from packages.infrastructure.llm.jd_extractor import extract_jd_fields

    board_info = extract_board_info(url)
    if board_info:
        raw_source_type = board_info[0]
    else:
        raw_source_type = "unknown"
    norm_source_type, norm_provider = normalize_source_type(raw_source_type)

    run_repo = RunRepository(db)
    task_repo = TaskRepository(db)
    run = run_repo.create(
        workspace_id=workspace.id,
        run_type="manual_import",
        input_snapshot_json={"url": url, "source": "manual_import"},
    )
    task = task_repo.create(
        run_id=run.id,
        workspace_id=workspace.id,
        task_type="manual_import",
        idempotency_key=f"manual_import:{workspace.id}:{url}",
    )
    db.flush()

    # Bind the LLM cost context now that run/task exist. extract_jd_fields()
    # below is the only LLM call in this handler; setting the context earlier
    # (before create/flush) left run_id/task_id/workspace_id empty and its
    # cost landed as an orphan row in the ledger.
    from packages.infrastructure.llm.usage_writer import set_llm_context
    set_llm_context(
        run_id=run.id,
        task_id=task.id,
        workspace_id=workspace.id,
        call_site="manual_import",
    )

    jd_fetched = False
    jd_text = None
    jd_hash = None
    jd_structured = None
    status = "discovered"
    title = ""
    company = ""
    location = None
    posted_at = None  # employer posting date, if the ATS board exposes one

    if board_info:
        from packages.domain.agent_jobs.ats_providers import build_api_url, parse_board_response
        import httpx
        provider, token = board_info
        api_url = build_api_url(provider, token)
        if api_url:
            try:
                resp = httpx.get(api_url, timeout=10.0)
                if resp.status_code == 200:
                    for bj in parse_board_response(provider, resp.json()):
                        if normalize_job_url(bj.url) == url:
                            title = bj.title
                            company = bj.company
                            location = bj.location
                            posted_at = bj.posted_at
                            break
            except Exception:
                pass
        if not company:
            company = token.replace("-", " ").title()

    fetch_result = None
    try:
        fetch_result = fetch_jd_from_url(url)
    except Exception:
        logger.warning("ingest_from_url: JD fetch failed for %s", url, exc_info=True)

    if fetch_result is not None and fetch_result.fetch_status == "doa":
        reason = (
            "closed_posting"
            if fetch_result.http_status == 200
            else f"http_{fetch_result.http_status or 'unknown'}"
        )
        DeadUrlRepository(db).record(
            url=url,
            reason=reason,
            http_status=fetch_result.http_status,
            discovered_run_id=run.id,
        )
        task_repo.mark_succeeded(task.id)
        run_repo.complete(
            run.id, status="succeeded", result_summary={"doa": True, "reason": reason}
        )
        db.commit()
        raise HTTPException(
            status_code=404,
            detail="This posting appears to be closed or no longer available.",
        )

    if fetch_result is not None and fetch_result.ok and fetch_result.jd_text:
        jd_text = fetch_result.jd_text
        jd_hash = fetch_result.jd_hash
        jd_fetched = True
        status = "reportable"
        try:
            jd_structured = extract_jd_fields(
                jd_text=jd_text,
                company=company,
                title=title,
                location=location or "",
                llm_client=get_llm_client(),
            )
        except Exception:
            logger.warning("ingest_from_url: JD extraction failed for %s", url, exc_info=True)

    if not title and jd_text:
        for line in jd_text.splitlines():
            line = line.strip()
            if line.lower().startswith("title:"):
                title = line[6:].strip()
                break
    if not title:
        slug = url.rstrip("/").split("/")[-1].split("?")[0]
        title = re.sub(r"[_-](?:JR?\d+)$", "", slug, flags=re.IGNORECASE).replace("-", " ").replace("_", " ").strip().title() or "Imported Job"
    if not company:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        company = hostname.split(".")[0].replace("-", " ").title() if hostname else ""

    job = job_repo.create(
        canonical_url=url,
        source_url=url,
        source_type=norm_source_type,
        source_provider=norm_provider,
        title=title,
        company=company,
        jd_text=jd_text,
        jd_hash=jd_hash,
        raw_payload_json={
            "source": "manual_import",
            "jd_structured": jd_structured,
            "fetch_status": "success" if jd_fetched else "failed",
        },
        status=status,
        discovered_run_id=run.id,
        discovered_task_id=task.id,
        posted_at=posted_at,
    )

    task_repo.mark_succeeded(task.id)
    run_repo.complete(run.id, status="succeeded", result_summary={
        "job_id": job.id,
        "jd_fetched": jd_fetched,
        "source": "manual_import",
    })
    db.commit()

    logger.info("ingest_from_url: created job %s from %s (status=%s)", job.id, url, status)
    return JobIngestResult(job=job, created=True, jd_fetched=jd_fetched)


def ingest_from_paste(
    db: Session,
    workspace: Workspace,
    *,
    company: str,
    title: str,
    jd_text: str,
) -> JobIngestResult:
    """Create a job row from a pasted JD (no URL). Runs the same content-quality
    gate + LLM extraction as the URL path, under a synthetic manual:// canonical
    url so the row dedups + feeds fit_report/resume_tailor like any other job."""
    from packages.infrastructure.jd_fetch.service import _validate_jd_text
    from packages.infrastructure.llm.client import get_llm_client
    from packages.infrastructure.llm.jd_extractor import extract_jd_fields
    from packages.infrastructure.llm.usage_writer import set_llm_context

    company = company.strip()
    title = title.strip()

    # Same content-quality gate the URL path applies to fetched text (≥200 chars,
    # not a CSS/JS page shell). Returns capped text + hash on success.
    validated = _validate_jd_text(jd_text.strip())
    if not validated.ok:
        raise HTTPException(status_code=422, detail=f"Pasted JD rejected: {validated.error}")
    jd_text = validated.jd_text
    jd_hash = validated.jd_hash

    # Synthetic canonical url: manual://<ws>/<md5(jd)[:16]>. The workspace id makes
    # it private + collision-free across workspaces; the content hash dedups a
    # re-paste of the same JD. Non-http scheme keeps the row out of every
    # fetch/reconciliation/dead-url path (all http-gated).
    digest = hashlib.md5(jd_text.encode("utf-8")).hexdigest()[:16]
    canonical = f"manual://{workspace.id}/{digest}"

    job_repo = JobRepository(db)
    existing = job_repo.get_by_canonical_url(canonical)
    if existing is not None:
        return JobIngestResult(
            job=existing, created=False, jd_fetched=existing.jd_text is not None
        )

    run_repo = RunRepository(db)
    task_repo = TaskRepository(db)
    run = run_repo.create(
        workspace_id=workspace.id,
        run_type="manual_import",
        input_snapshot_json={"source": "manual_paste", "canonical_url": canonical},
    )
    task = task_repo.create(
        run_id=run.id,
        workspace_id=workspace.id,
        task_type="manual_import",
        idempotency_key=f"manual_import:{workspace.id}:{canonical}",
    )
    db.flush()

    set_llm_context(
        run_id=run.id,
        task_id=task.id,
        workspace_id=workspace.id,
        call_site="manual_paste",
    )

    jd_structured = None
    try:
        jd_structured = extract_jd_fields(
            jd_text=jd_text,
            company=company,
            title=title,
            location="",
            llm_client=get_llm_client(),
        )
    except Exception:
        logger.warning("ingest_from_paste: JD extraction failed for %s", canonical, exc_info=True)

    job = job_repo.create(
        canonical_url=canonical,
        source_url=canonical,
        source_type="manual_paste",
        source_provider=None,
        title=title or "Pasted Job",
        company=company,
        jd_text=jd_text,
        jd_hash=jd_hash,
        raw_payload_json={
            "source": "manual_paste",
            "jd_structured": jd_structured,
            "fetch_status": "success",
        },
        status="reportable",
        discovered_run_id=run.id,
        discovered_task_id=task.id,
    )

    task_repo.mark_succeeded(task.id)
    run_repo.complete(run.id, status="succeeded", result_summary={
        "job_id": job.id,
        "jd_fetched": True,
        "source": "manual_paste",
    })
    db.commit()

    logger.info("ingest_from_paste: created job %s (%s)", job.id, canonical)
    return JobIngestResult(job=job, created=True, jd_fetched=True)
