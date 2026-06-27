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
from packages.infrastructure.agent_runtime.openclaw import create_runtime
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
    runtime = create_runtime()

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

    if result.usage:
        from packages.infrastructure.llm.usage_writer import persist_agent_usage
        persist_agent_usage(
            run_id=env.run_id, task_id=env.task_id,
            workspace_id=env.workspace_id, call_site="agent.job_research",
            model=result.usage.model, input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
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

        # Backfill JD text into the jobs table and promote to reportable.
        # The research agent fetches the JD from source_url and writes it
        # to the manifest so the worker can persist it here without doing IO.
        if manifest.jd_text:
            jd_hash = hashlib.md5(manifest.jd_text.encode()).hexdigest()[:16]
            job_repo.update_jd(job_id, manifest.jd_text, jd_hash)
            job_repo.set_status(job_id, "reportable")
            logger.info(
                "research_run: backfilled jd_text for job_id=%s (hash=%s), status→reportable",
                job_id,
                jd_hash,
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
                "jd_backfilled": bool(manifest.jd_text),
            },
        )
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=(
                f"Research complete: job_id={job_id}, "
                f"citations={manifest.citations_count}, "
                f"jd_backfilled={bool(manifest.jd_text)}"
            ),
        )

    logger.info(
        "research_run: task_id=%s succeeded, job_id=%s citations=%d jd_backfilled=%s",
        env.task_id,
        job_id,
        manifest.citations_count,
        bool(manifest.jd_text),
    )
    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "job_id": job_id,
        "citations_count": manifest.citations_count,
        "jd_backfilled": bool(manifest.jd_text),
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
