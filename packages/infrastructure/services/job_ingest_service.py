"""
JobIngestService — the single deterministic job-ingest pipeline behind both the
URL importer and the paste importer (one machine, two feed chutes).

Entry points:
  ingest_from_url(db, workspace, url)                       — fetch + extract a JD from a URL
  ingest_from_paste(db, workspace, company, title, jd_text) — a pasted JD, no URL

Both build a run/task (run_type="manual_import"), bind the LLM cost context, run
the shared extract/create path, and return a JobIngestResult (raw Job ORM row +
created + jd_fetched flags; the API route builds JobImportResponse via _job_read).

The URL path resolves identity (title/company/location) through a cascade that
ends in reading rather than guessing: ATS board API → schema.org markup → the
page itself via a cheap LLM with a verbatim-evidence gate. When all of them
come up empty the import is refused. There is deliberately no URL-derived
fallback — it could not fail, so an unreadable page became a row titled with a
URL slug that nothing downstream could tell was wrong.

Otherwise the URL path preserves import_job's original semantics (3-level
fetch, DOA/dead-url recording, cross-workspace dedup → 409). The paste path synthesizes
a manual://<ws>/<md5(jd)> canonical url so the row dedups + references like any
other job, but — being a non-http scheme — never re-enters the fetch /
reconciliation / dead-url machinery (those all guard on http(s) already; see the
W1 http-assumption audit note in apps/api/routes/jobs.py).

Note: raises fastapi.HTTPException for the caller-facing error cases (bad
scheme / blocked aggregator 400 / cross-workspace 409 / DOA 404 / unreadable
posting 422 / unidentifiable posting 422 / paste-JD rejected 422).
"""
from __future__ import annotations

import hashlib
import logging
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

# Aggregators that cannot be fetched at all — not "usually fails", but blocked
# by design behind a login wall or a browser challenge, on every tier we have.
# Rejecting at the door beats letting the fetch tiers grind through and return
# a generic "couldn't read this posting": the user gets told what is actually
# wrong and what to do instead, one round trip sooner. Matched on the
# registrable domain, so regional and www subdomains are covered too.
# Add a domain only with a real failed import behind it.
_BLOCKED_DOMAINS = {
    "linkedin.com": (
        "LinkedIn requires login to view job postings. Please use the direct "
        "employer or ATS URL instead."
    ),
    # Cloudflare challenge; verified unreachable via direct fetch (403 with a
    # browser user-agent too) and via the Jina renderer, which returns the
    # "Just a moment..." interstitial rather than the posting.
    "indeed.com": (
        "Indeed requires browser verification and cannot be read automatically. "
        "Use the employer's own posting (their careers site or ATS link), or "
        "paste the job description text instead."
    ),
}


def _blocked_domain_message(hostname: str | None) -> str | None:
    host = (hostname or "").lower()
    for domain, message in _BLOCKED_DOMAINS.items():
        if host == domain or host.endswith(f".{domain}"):
            return message
    return None


@dataclass
class JobIngestResult:
    """Raw ingest outcome; the route maps `.job` through _job_read into the API
    JobImportResponse (which needs route-layer helpers that can't live here)."""

    job: Job
    created: bool
    jd_fetched: bool


def ingest_from_url(db: Session, workspace: Workspace, url: str) -> JobIngestResult:
    """Import a single job by URL: fetch JD, extract fields, persist.

    Refuses (422) when the URL yields neither a JD nor a title — see the guard
    below for why a URL-guessed row is worse than no row at all."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    from urllib.parse import urlparse
    blocked = _blocked_domain_message(urlparse(url).hostname)
    if blocked:
        raise HTTPException(status_code=400, detail=blocked)

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
        # Keyed on the run, per the convention elsewhere — NOT on the url.
        # tasks.idempotency_key is UNIQUE, and every path that ends without a
        # job row (DOA, and now an unreadable posting) still commits its task,
        # so a url-keyed retry of the same import collided and surfaced as a
        # 500. Re-import dedup is the canonical_url lookup above, not this key.
        idempotency_key=f"manual_import:{workspace.id}:{run.id}",
    )
    # Committed, not flushed. The cost ledger writes from its own DB session,
    # so a merely-flushed run is invisible to it: the usage event's foreign key
    # fails, the writer swallows it (it is fire-and-forget by design, so an
    # accounting problem can't break a user's import), and the charge is lost.
    # That is how binding run_id below — which fixed usage events landing as
    # orphans — turned "recorded but unattributable" into "not recorded at all"
    # for every manual import after 2026-07-10.
    #
    # The cost of committing here is one stranded `queued` run if the process
    # dies mid-import. It is bounded: every path that finishes (success, DOA,
    # unreadable, unidentifiable) already commits run/task before returning, and
    # manual_import is not one of the run types under the active-run uniqueness
    # index, so a stranded row cannot block the next import.
    db.commit()

    # Bind the LLM cost context now that run/task are durable. Setting it
    # earlier (before create/commit) left run_id/task_id/workspace_id empty and
    # the cost landed as an orphan row in the ledger.
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

    # Posting identity as the ATS reported it, when a structured tier resolved
    # the URL (board listing, or a Greenhouse board embedded in a company
    # careers page). Adopted before the extraction below so the LLM sees the
    # real title/company rather than a URL guess.
    if fetch_result is not None:
        title = title or (fetch_result.title or "").strip()
        company = company or (fetch_result.company or "").strip()
        location = location or fetch_result.location
        posted_at = posted_at or fetch_result.posted_at

    if fetch_result is not None and fetch_result.ok and fetch_result.jd_text:
        jd_text = fetch_result.jd_text
        jd_hash = fetch_result.jd_hash
        jd_fetched = True
        status = "reportable"

    if not title and jd_text:
        for line in jd_text.splitlines():
            line = line.strip()
            if line.lower().startswith("title:"):
                title = line[6:].strip()
                break

    # Nothing structured resolved the identity, but the page is readable — so
    # read it. This is the general channel behind the vendor-specific ones
    # (board API, schema.org markup); without it, an employer-built portal that
    # renders a real JD with no machine-readable identity falls through to
    # whatever the URL string happens to look like. Cheap model, verified
    # output, and only on the paths that need it — a posting whose ATS already
    # named it never gets here.
    if jd_text and (not title or not company):
        from packages.infrastructure.llm.identity_extractor import extract_job_identity

        try:
            identity = extract_job_identity(
                page_text=jd_text, url=url, llm_client=get_llm_client()
            )
        except Exception:
            # The extractor swallows its own failures; this is the belt to that
            # brace. It matters which way it fails: an unknown identity must
            # land on the refusal below, never on a 500 and never on a row.
            logger.warning("ingest_from_url: identity extraction raised for %s", url, exc_info=True)
            identity = None
        if identity is not None:
            title = title or (identity.title or "")
            company = company or (identity.company or "")
            location = location or identity.location

    # With no JD text *and* no title from any structured source, there is
    # nothing to build a row out of. The paste path is the way in for a posting
    # we can't read.
    if not jd_fetched and not title:
        task_repo.mark_failed(
            task.id, "jd_unreadable", f"No readable job posting at {url}"
        )
        run_repo.complete(
            run.id,
            status="failed",
            result_summary={
                "source": "manual_import",
                "reason": "jd_unreadable",
                "fetch_status": fetch_result.fetch_status if fetch_result else "error",
            },
        )
        db.commit()
        logger.info("ingest_from_url: refused unreadable posting %s", url)
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not read this posting — no job description or title was "
                "found at that URL (often a login wall, or a board that renders "
                "only in a browser). Paste the job description text instead."
            ),
        )

    # The JD is readable but no channel could say what job it is. There used to
    # be a guess here — slug -> title, hostname -> company — and it is gone on
    # purpose: it turned "we could not read this page" into a row titled
    # "169151" at a company called "Higher", indistinguishable in the UI from a
    # row that was read correctly. Refusing costs the user a paste; the guess
    # cost them a wrong row they had no way to spot.
    if not title:
        task_repo.mark_failed(
            task.id, "identity_unresolved", f"No job title could be read from {url}"
        )
        run_repo.complete(
            run.id,
            status="failed",
            result_summary={
                "source": "manual_import",
                "reason": "identity_unresolved",
                "fetch_status": fetch_result.fetch_status if fetch_result else "error",
            },
        )
        db.commit()
        logger.info("ingest_from_url: refused unidentifiable posting %s", url)
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not determine the job title from this page. The posting "
                "text was readable but the title was not — paste the job "
                "description text instead."
            ),
        )
    # company may stay empty: an unbranded page is a blank field, not a reason
    # to name the website as the employer.

    # Identity is settled, so the JD extractor sees the real title/company as
    # context rather than a placeholder. Runs last because a refusal above
    # means no row — and no reason to spend tokens on one.
    if jd_fetched and jd_text:
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

    job = job_repo.create(
        canonical_url=url,
        source_url=url,
        source_type=norm_source_type,
        source_provider=norm_provider,
        title=title,
        company=company,
        jd_text=jd_text,
        jd_hash=jd_hash,
        location=location or None,
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
    # Committed before the LLM call, so the cost ledger's own session can see
    # the run this charge belongs to — see the URL path for the full reasoning.
    db.commit()

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
