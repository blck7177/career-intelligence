"""
Handler for agent.job_research tasks.

Execution mode: OPENCLAW
Agent: career-research-agent
Skill: career-research-operator

Full flow (per architecture.md Agent Execution Flow):
  1. Read run/task from Postgres
  2. Build AgentInvocationSpec (via domain/agent_jobs/planner)
  3. Build AgentTaskInput → write to input.json on agent_artifacts volume
  4. Create agent_invocation record in DB
  5. Call OpenClawRuntime.invoke(spec)
  6. Update agent_invocation with exit_code / timing
  7. Read output_manifest.json
  8. Run ValidatorGate (schema + provenance)
  9. Persist validation results
  10. Pass → write artifacts to DB, mark task succeeded
  11. Fail → mark task needs_review, no artifact writes
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from packages.contracts.agents.invocation import AgentBudget, AgentTaskInput
from packages.contracts.agents.manifests import AgentOutputManifest, ResearchManifest
from packages.contracts.api.runs import JobResearchInput
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.domain.agent_jobs.planner import build_invocation_spec, build_task_input
from packages.infrastructure.agent_runtime.openclaw_http import create_http_runtime
from packages.infrastructure.agent_runtime.validator import ValidatorGate
from packages.infrastructure.db.repositories import (
    AgentInvocationRepository,
    AgentValidationResultRepository,
    ArtifactRepository,
    JobRepository,
    RunRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session
from packages.infrastructure.jd_fetch.service import MIN_JD_TEXT_LEN

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")


def handle_research_run(env: TaskEnvelope) -> dict:
    """
    Entry point for agent.job_research tasks.
    Called by execute_task when task_type == "agent.job_research".
    """
    logger.info("research_run: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    # ------------------------------------------------------------------
    # Step 1: Read run context from Postgres
    # ------------------------------------------------------------------
    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        input_snapshot = run.input_snapshot_json or {}
        workspace_id = env.workspace_id

    try:
        inp = JobResearchInput.model_validate(input_snapshot)
    except ValidationError as exc:
        logger.error("research_run: invalid input_snapshot: %s", exc)
        _mark_needs_review(
            env,
            invocation_id="",
            reason=f"Invalid job_research input_snapshot: {exc}",
            error_code="INVALID_INPUT",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # Look up the job record so the agent gets company/title/source_url —
    # the API only requires job_id (JobResearchInput), but the research
    # skill (research_io.md) expects these to already be in the payload.
    # DB is the authoritative source; it overrides any caller-supplied values.
    with get_session() as session:
        job = JobRepository(session).get(inp.job_id)
        if job is None:
            logger.error("research_run: job not found: %s", inp.job_id)
            _mark_needs_review(
                env,
                invocation_id="",
                reason=f"Job not found: {inp.job_id}",
                error_code="JOB_NOT_FOUND",
            )
            return {"status": "needs_review", "task_id": env.task_id}
        job_context = {
            "company": job.company,
            "title": job.title,
            "source_url": job.canonical_url,
        }

    # ------------------------------------------------------------------
    # Step 2: Build AgentInvocationSpec
    # ------------------------------------------------------------------
    budget = AgentBudget(
        max_tool_calls=inp.max_tool_calls,
        timeout_seconds=inp.timeout_seconds,
    )

    import uuid as _uuid
    unified_invocation_id = str(_uuid.uuid4())

    spec = build_invocation_spec(
        run_id=env.run_id,
        task_id=env.task_id,
        workspace_id=workspace_id,
        task_type=env.task_type,
        attempt=env.attempt,
        artifacts_base_dir=_ARTIFACTS_DIR,
        payload=input_snapshot,
        budget=budget,
        invocation_id=unified_invocation_id,
    )

    # ------------------------------------------------------------------
    # Step 3: Build input.json and write to artifact volume
    # ------------------------------------------------------------------
    run_dir = Path(_ARTIFACTS_DIR) / env.run_id / env.task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Inject platform-canonical output paths so the research agent knows where
    # to write research_notes.md, research_sources.json, and fetch_ledger.jsonl.
    # The client cannot know these paths at run-creation time (task_id is
    # assigned by the worker), so the worker injects them here.
    enriched_payload = {
        **input_snapshot,
        **job_context,
        "expected_output_paths": {
            "research_notes": str(run_dir / "research_notes.md"),
            "research_sources": str(run_dir / "research_sources.json"),
            "fetch_ledger": str(run_dir / "research_fetch_ledger.jsonl"),
        },
    }

    task_input = build_task_input(
        spec=spec,
        task_type=env.task_type,
        payload=enriched_payload,
        budget=budget,
    )

    input_json_path = Path(spec.input_spec_path)
    input_json_path.write_text(task_input.model_dump_json(indent=2))
    logger.info("research_run: wrote input.json to %s", input_json_path)

    # ------------------------------------------------------------------
    # Step 4: Create agent_invocation record
    # ------------------------------------------------------------------
    with get_session() as session:
        inv_repo = AgentInvocationRepository(session)
        event_repo = TaskEventRepository(session)

        invocation = inv_repo.create(
            run_id=env.run_id,
            task_id=env.task_id,
            workspace_id=workspace_id,
            agent_id=spec.agent_id,
            session_key=spec.session_key,
            skill_contract_version=spec.skill_contract_version,
            input_spec_uri=str(input_json_path),
            output_manifest_uri=spec.output_manifest_path,
            id=unified_invocation_id,
        )
        invocation_id = invocation.id

        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="agent_invocation_created",
            message=f"Invocation {invocation_id} created (agent={spec.agent_id})",
        )

    # ------------------------------------------------------------------
    # Step 5: Invoke OpenClaw
    # ------------------------------------------------------------------
    runtime = create_http_runtime()

    with get_session() as session:
        inv_repo = AgentInvocationRepository(session)
        inv_repo.mark_running(invocation_id)
        event_repo = TaskEventRepository(session)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="agent_invocation_started",
            message=f"OpenClaw invoked: agent={spec.agent_id} session={spec.session_key[:60]}",
        )

    result = runtime.invoke(spec)

    # Record usage BEFORE any other post-invoke step — result.usage reflects
    # a real, already-billed charge the moment invoke() returns, and a disk
    # or DB error further down must not be able to drop it.
    if result.usage:
        from packages.infrastructure.llm.usage_writer import persist_agent_usage
        persist_agent_usage(
            run_id=env.run_id, task_id=env.task_id,
            workspace_id=env.workspace_id, call_site="agent.job_research",
            model=result.usage.model, input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_tokens=result.usage.cache_read_tokens,
        )

    # ------------------------------------------------------------------
    # Step 6: Update invocation record with result
    # ------------------------------------------------------------------
    stdout_path: str | None = None
    stderr_path: str | None = None

    if result.stdout:
        p = run_dir / "stdout.txt"
        p.write_text(result.stdout)
        stdout_path = str(p)
    if result.stderr:
        p = run_dir / "stderr.txt"
        p.write_text(result.stderr)
        stderr_path = str(p)

    with get_session() as session:
        inv_repo = AgentInvocationRepository(session)
        inv_repo.mark_finished(
            invocation_id,
            exit_code=result.exit_code,
            stdout_uri=stdout_path,
            stderr_uri=stderr_path,
            error_code="AGENT_EXIT_NONZERO" if result.exit_code != 0 else None,
            error_message=result.stderr[:500] if result.exit_code != 0 else None,
        )

    if result.exit_code != 0 or result.timed_out:
        error_code = "AGENT_TIMEOUT" if result.timed_out else "AGENT_EXIT_NONZERO"
        reason = (
            f"Agent invocation timed out after {spec.timeout_seconds}s"
            if result.timed_out
            else f"Agent invocation failed with exit_code={result.exit_code}"
        )
        if result.stderr:
            reason = f"{reason}: {result.stderr[:500]}"
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason=reason,
            error_code=error_code,
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 7–8: Read output manifest and run Validator Gate
    # ------------------------------------------------------------------
    manifest_path = Path(spec.output_manifest_path)

    if not manifest_path.exists():
        logger.error(
            "research_run: output_manifest.json not found at %s", manifest_path
        )
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason="output_manifest.json not found after agent completion",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    try:
        raw = json.loads(manifest_path.read_text())
        manifest = ResearchManifest.model_validate(raw)
    except Exception as exc:
        logger.exception("research_run: failed to parse output_manifest.json: %s", exc)
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason=f"output_manifest.json parse error: {exc}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # Strip platform-supplementary artifacts that may be declared but not
    # created (e.g. fetch_ledger if the agent used native web_fetch instead
    # of career_fetch_source.py wrapper). The validator will fail on missing
    # declared artifacts, so we remove optional ones that don't exist.
    _strip_missing_optional_artifacts(manifest, optional_keys={"fetch_ledger"})

    gate = ValidatorGate()
    validation_results = gate.run(manifest, spec)

    # ------------------------------------------------------------------
    # Step 9: Persist validation results
    # ------------------------------------------------------------------
    with get_session() as session:
        val_repo = AgentValidationResultRepository(session)
        for vr in validation_results:
            val_repo.create(
                invocation_id=invocation_id,
                validator_name=vr.validator_name,
                status=vr.status,
                errors_json=[e.model_dump() for e in vr.errors],
                warnings_json=[w.model_dump() for w in vr.warnings],
            )

    # ------------------------------------------------------------------
    # Step 10/11: Pass → write artifacts; Fail → needs_review
    # ------------------------------------------------------------------
    if not gate.all_passed(validation_results):
        failed_validators = [r.validator_name for r in validation_results if r.status == "failed"]
        logger.warning(
            "research_run: validator gate FAILED for task %s: %s",
            env.task_id,
            failed_validators,
        )
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason=f"Validator gate failed: {failed_validators}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    job_id = manifest.job_id

    with get_session() as session:
        artifact_repo = ArtifactRepository(session)
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        job_repo = JobRepository(session)

        for artifact_type, path_str in manifest.artifact_paths.items():
            artifact_repo.create(
                run_id=env.run_id,
                task_id=env.task_id,
                artifact_type=artifact_type,
                storage_uri=path_str,
                content_hash=_compute_file_sha256(path_str),
                metadata_json={"invocation_id": invocation_id, "job_id": job_id},
            )

        # Backfill JD text into the jobs table. The research agent fetches the
        # JD from source_url and writes it to the manifest so the worker can
        # persist it here without doing IO — or, when source_url doesn't expose
        # readable JD text, from a verified third-party mirror repost instead.
        # manifest.jd_source_type is the agent's own claim about which case this
        # is, but it's self-reported prose-adjacent metadata from an LLM and has
        # been observed to default to "original" even when the agent's own notes
        # describe the content as a mirror — so it is NOT trusted as the sole
        # safety signal. Instead we always check for a company+title collision
        # before auto-promoting: if another job shares that company+title, we
        # can't be sure the fetched text is tied to *this* specific posting
        # (e.g. multiple concurrent postings with an identical title), so it
        # stays in 'discovered' for review regardless of claimed source_type.
        promoted = False
        if manifest.jd_text and len(manifest.jd_text) >= MIN_JD_TEXT_LEN:
            jd_hash = hashlib.md5(manifest.jd_text.encode()).hexdigest()[:16]
            job_repo.update_jd(job_id, manifest.jd_text, jd_hash)
            job_repo.merge_raw_payload(job_id, {"jd_source": f"research_{manifest.jd_source_type}"})

            job = job_repo.get_or_raise(job_id)
            collision = job_repo.has_company_title_collision(job.company, job.title, job_id)
            if collision:
                logger.warning(
                    "research_run: jd_text backfilled for job_id=%s (claimed source=%s) but "
                    "company+title matches another job — leaving status=discovered for review",
                    job_id, manifest.jd_source_type,
                )
            else:
                job_repo.set_status(job_id, "reportable")
                promoted = True

            logger.info(
                "research_run: backfilled jd_text for job_id=%s (hash=%s, source=%s, promoted=%s)",
                job_id, jd_hash, manifest.jd_source_type, promoted,
            )
        elif manifest.jd_text:
            logger.warning(
                "research_run: manifest.jd_text too short for job_id=%s (%d chars, min %d) — "
                "not backfilled, job stays in 'discovered' status",
                job_id, len(manifest.jd_text), MIN_JD_TEXT_LEN,
            )
        else:
            logger.warning(
                "research_run: manifest.jd_text missing for job_id=%s; "
                "job stays in 'discovered' status, report generation will use JD-only fallback",
                job_id,
            )

        task_repo.mark_succeeded(env.task_id)
        run_repo = RunRepository(session)
        run_repo.complete(
            env.run_id,
            status="succeeded",
            result_summary={
                "job_id": job_id,
                "citations_count": manifest.citations_count,
                "jd_backfilled": promoted,
            },
        )
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=(
                f"Research complete: job_id={job_id}, "
                f"citations={manifest.citations_count}, "
                f"jd_backfilled={promoted}"
            ),
        )

    logger.info(
        "research_run: task_id=%s succeeded, job_id=%s citations=%d jd_backfilled=%s",
        env.task_id,
        job_id,
        manifest.citations_count,
        promoted,
    )
    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "job_id": job_id,
        "citations_count": manifest.citations_count,
        "jd_backfilled": promoted,
    }


def _strip_missing_optional_artifacts(
    manifest: ResearchManifest,
    optional_keys: set[str],
) -> None:
    """
    Remove declared artifact_paths entries that are optional and whose files
    don't exist on disk.  The ProvenanceValidator fails hard on any declared
    artifact that is missing, so we drop optional keys here to avoid blocking
    research tasks on supplementary artifacts.
    """
    for key in list(optional_keys):
        if key in manifest.artifact_paths:
            path = Path(manifest.artifact_paths[key])
            if not path.exists():
                logger.warning(
                    "research_run: optional artifact %r not found at %s — removing from manifest",
                    key,
                    path,
                )
                del manifest.artifact_paths[key]


def _compute_file_sha256(path_str: str) -> str | None:
    """Return sha256:<hex> for the file at path_str, or None if unreadable."""
    try:
        digest = hashlib.sha256(Path(path_str).read_bytes()).hexdigest()
        return f"sha256:{digest}"
    except OSError:
        return None


def _mark_needs_review(
    env: TaskEnvelope,
    *,
    invocation_id: str,
    reason: str,
    error_code: str = "VALIDATOR_GATE_FAILED",
) -> None:
    with get_session() as session:
        task_repo = TaskRepository(session)
        run_repo = RunRepository(session)
        event_repo = TaskEventRepository(session)
        task_repo.mark_needs_review(
            env.task_id,
            error_code=error_code,
            error_message=reason[:500],
        )
        run_repo.complete(
            env.run_id,
            status="needs_review",
            result_summary={"error_code": error_code, "invocation_id": invocation_id},
        )
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_needs_review",
            message=reason,
        )
