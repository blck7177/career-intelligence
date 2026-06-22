"""
Handler for agent.job_discovery tasks.

Execution mode: OPENCLAW
Agent: career-search-agent
Skill: career-search-operator

Full flow (per architecture.md Agent Execution Flow):
  1.  Read run/task from Postgres
  1b. Parse input_snapshot → JobDiscoveryFrontendInput
  1c. Load ProfileSnapshot (empty default for MVP)
  1d. IntentTranslator.translate() → DiscoveryIntent  [LLM call]
      Emit task_event(intent_translated)
  2.  Build AgentInvocationSpec (via domain/agent_jobs/planner)
  3.  Build DiscoveryTaskSpec → write to input.json on agent_artifacts volume
  4.  Create agent_invocation record in DB
  5.  Call OpenClawRuntime.invoke(spec)
  6.  Update agent_invocation with exit_code / timing
  7.  Read output_manifest.json
  8.  Run ValidatorGate (schema + provenance + budget)
  9.  Persist validation results
  10. Pass → write artifacts to DB, mark task succeeded
  11. Fail → mark task needs_review, no artifact writes
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from packages.contracts.agents.discovery_intent import ProfileSnapshot
from packages.contracts.agents.invocation import AgentBudget, AgentTaskInput
from packages.contracts.agents.manifests import AgentOutputManifest, DiscoveryManifest
from packages.contracts.api.discovery import JobDiscoveryFrontendInput
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.domain.agent_jobs.discovery_planner import (
    build_discovery_task_spec,
    budget_for_depth,
)
from packages.domain.agent_jobs.planner import build_invocation_spec
from packages.infrastructure.agent_runtime.openclaw import create_runtime
from packages.infrastructure.agent_runtime.validator import ValidatorGate
from packages.infrastructure.db.repositories import (
    AgentInvocationRepository,
    AgentValidationResultRepository,
    ArtifactRepository,
    RunRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session
from packages.infrastructure.llm.client import get_llm_client
from packages.infrastructure.llm.intent_translator import (
    IntentTranslationError,
    IntentTranslator,
)

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")


def handle_search_run(env: TaskEnvelope) -> dict:
    """
    Entry point for agent.job_discovery tasks.
    Called by execute_task when ExecutionMode == OPENCLAW.
    """
    logger.info("search_run: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    # ------------------------------------------------------------------
    # Step 1: Read run context from Postgres
    # ------------------------------------------------------------------
    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        TaskRepository(session).get_or_raise(env.task_id)
        input_snapshot = run.input_snapshot_json or {}
        workspace_id = env.workspace_id

    # ------------------------------------------------------------------
    # Step 1b: Parse input_snapshot → JobDiscoveryFrontendInput
    # ------------------------------------------------------------------
    try:
        frontend_input = JobDiscoveryFrontendInput.model_validate(input_snapshot)
    except ValidationError as exc:
        logger.error("search_run: invalid frontend input: %s", exc)
        _mark_needs_review(
            env,
            invocation_id=None,
            reason=f"Invalid job_discovery input_snapshot: {exc}",
            error_code="INVALID_FRONTEND_INPUT",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 1c: Load ProfileSnapshot (MVP: always empty default)
    # ------------------------------------------------------------------
    profile_snapshot = _load_profile(frontend_input.profile_id)

    # ------------------------------------------------------------------
    # Step 1c.5: Guard — profile_guided requires a non-empty profile
    # ------------------------------------------------------------------
    if frontend_input.search_mode == "profile_guided" and profile_snapshot.is_empty:
        logger.warning(
            "search_run: profile_guided requested but no valid profile available "
            "(profile_id=%r) — marking needs_review",
            frontend_input.profile_id,
        )
        _mark_needs_review(
            env,
            invocation_id=None,
            reason=(
                "search_mode=profile_guided requires a valid profile, "
                f"but no profile is available (profile_id={frontend_input.profile_id!r}). "
                "Please provide a profile or switch to exploratory mode."
            ),
            error_code="PROFILE_REQUIRED_FOR_PROFILE_GUIDED",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 1d: Intent Translation (LLM call)
    # ------------------------------------------------------------------
    with get_session() as session:
        event_repo = TaskEventRepository(session)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="intent_translation_started",
            message=(
                f"Translating intent: mode={frontend_input.search_mode} "
                f"depth={frontend_input.search_depth} "
                f"profile={'provided' if not profile_snapshot.is_empty else 'none'}"
            ),
        )

    translator = IntentTranslator(llm_client=get_llm_client())
    try:
        discovery_intent = translator.translate(
            frontend_input=frontend_input,
            profile_snapshot=profile_snapshot,
        )
    except IntentTranslationError as exc:
        logger.error(
            "search_run: intent translation failed (kind=%s): %s", exc.kind, exc
        )
        error_code = (
            "INTENT_BLOCKING_AMBIGUITY"
            if exc.kind == "blocking_ambiguity"
            else "INTENT_TRANSLATION_FAILED"
        )
        _mark_needs_review(
            env,
            invocation_id=None,
            reason=str(exc),
            error_code=error_code,
        )
        return {"status": "needs_review", "task_id": env.task_id}

    with get_session() as session:
        event_repo = TaskEventRepository(session)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="intent_translated",
            message=discovery_intent.interpreted_goal,
            payload_json=discovery_intent.model_dump(mode="json"),
        )

    logger.info(
        "search_run: intent translated — goal=%r lanes=%d flags=%d",
        discovery_intent.interpreted_goal[:80],
        len(discovery_intent.target_role_families),
        len(discovery_intent.ambiguity_flags),
    )

    # ------------------------------------------------------------------
    # Step 2: Build AgentInvocationSpec
    # ------------------------------------------------------------------
    budget = budget_for_depth(frontend_input.search_depth)

    spec = build_invocation_spec(
        run_id=env.run_id,
        task_id=env.task_id,
        workspace_id=workspace_id,
        task_type=env.task_type,
        attempt=env.attempt,
        artifacts_base_dir=_ARTIFACTS_DIR,
        payload={},  # payload is built separately below via DiscoveryTaskSpec
        budget=budget,
    )

    # ------------------------------------------------------------------
    # Step 3: Build DiscoveryTaskSpec and write to input.json
    # ------------------------------------------------------------------
    task_spec = build_discovery_task_spec(
        discovery_intent=discovery_intent,
        search_depth=frontend_input.search_depth,
        artifacts_dir=_ARTIFACTS_DIR,
        run_id=env.run_id,
        task_id=env.task_id,
        # MVP: catalog_context, source_registry_snapshot, previous_run_diagnostics
        # are all None. Future: planner queries DB to populate these.
    )

    # Wrap into AgentTaskInput using DiscoveryTaskSpec as the payload
    task_input = AgentTaskInput(
        invocation_id=spec.invocation_id,
        run_id=spec.run_id,
        task_id=spec.task_id,
        workspace_id=spec.workspace_id,
        task_type=env.task_type,
        skill_contract_version=spec.skill_contract_version,
        output_manifest_path=task_spec.output_paths.output_manifest_path,
        budget=budget,
        payload=task_spec.model_dump(mode="json"),
    )

    run_dir = Path(_ARTIFACTS_DIR) / env.run_id / env.task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    input_json_path = Path(spec.input_spec_path)
    input_json_path.write_text(task_input.model_dump_json(indent=2))
    logger.info("search_run: wrote input.json to %s", input_json_path)

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
            output_manifest_uri=task_spec.output_paths.output_manifest_path,
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
    manifest_path = Path(task_spec.output_paths.output_manifest_path)

    if not manifest_path.exists():
        logger.error(
            "search_run: output_manifest.json not found at %s", manifest_path
        )
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason="output_manifest.json not found after agent completion",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    try:
        raw = json.loads(manifest_path.read_text())
        manifest = DiscoveryManifest.model_validate(raw)
    except Exception as exc:
        logger.exception("search_run: failed to parse output_manifest.json: %s", exc)
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason=f"output_manifest.json parse error: {exc}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 7.5: Normalize candidate_pool artifact
    # ------------------------------------------------------------------
    # The agent may write a JSON array instead of JSONL, or omit the file
    # entirely when there are zero candidates.  Normalize here so the
    # ValidatorGate always sees consistent JSONL content.
    _normalize_candidate_pool(manifest, run_dir)

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
            "search_run: validator gate FAILED for task %s: %s",
            env.task_id,
            failed_validators,
        )
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason=f"Validator gate failed: {failed_validators}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    with get_session() as session:
        artifact_repo = ArtifactRepository(session)
        task_repo = TaskRepository(session)
        run_repo = RunRepository(session)
        event_repo = TaskEventRepository(session)

        for artifact_type, path_str in manifest.artifact_paths.items():
            artifact_repo.create(
                run_id=env.run_id,
                task_id=env.task_id,
                artifact_type=artifact_type,
                storage_uri=path_str,
                metadata_json={"invocation_id": invocation_id},
            )

        task_repo.mark_succeeded(env.task_id)
        run_repo.set_status(env.run_id, "succeeded")
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=(
                f"Discovery complete: {manifest.candidate_count} candidates, "
                f"{len(manifest.sources_tried)} sources tried"
            ),
        )

    logger.info(
        "search_run: task_id=%s succeeded, candidates=%d",
        env.task_id,
        manifest.candidate_count,
    )
    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "candidate_count": manifest.candidate_count,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_candidate_pool(manifest: DiscoveryManifest, run_dir: Path) -> None:
    """
    Ensure candidate_pool artifact is valid JSONL before the validator gate runs.

    Two cases we fix:
      1. Agent wrote a JSON array  → convert to one JSON object per line (JSONL).
      2. Zero-candidate run with no pool artifact → create an empty file and
         register it in the manifest so the validator sees a consistent artifact.

    This is worker-side normalization: we prefer fixing the format here rather
    than loosening the validator contract.
    """
    pool_path_str = manifest.artifact_paths.get("candidate_pool")

    if pool_path_str:
        pool_path = Path(pool_path_str)
        if pool_path.exists() and pool_path.stat().st_size > 0:
            try:
                raw = pool_path.read_text().strip()
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    # Convert JSON array to JSONL in-place.
                    lines = "\n".join(json.dumps(item) for item in parsed)
                    pool_path.write_text(lines + "\n" if lines else "")
                    logger.info(
                        "search_run: normalized candidate_pool from JSON array "
                        "to JSONL (%d records) at %s",
                        len(parsed),
                        pool_path,
                    )
                # If it's already a dict (single object without newlines) wrap it.
                elif isinstance(parsed, dict):
                    pool_path.write_text(json.dumps(parsed) + "\n")
                    logger.info(
                        "search_run: normalized candidate_pool from bare JSON "
                        "object to JSONL at %s",
                        pool_path,
                    )
                # Otherwise it's already JSONL or some other structure — leave it
                # for the validator to catch.
            except json.JSONDecodeError:
                # Already JSONL or invalid — validator will surface the error.
                pass
        return

    # No candidate_pool in manifest at all.
    if manifest.candidate_count == 0:
        # Create an empty file so the validator sees a declared artifact.
        empty_path = run_dir / "candidate_pool.jsonl"
        empty_path.touch()
        manifest.artifact_paths["candidate_pool"] = str(empty_path)
        logger.info(
            "search_run: created empty candidate_pool.jsonl for zero-candidate "
            "run at %s",
            empty_path,
        )


def _load_profile(profile_id: str | None) -> ProfileSnapshot:
    """
    Load a ProfileSnapshot for the given profile_id.

    MVP: always returns an empty profile. Future: query workspace_profiles
    table and return a populated snapshot.
    """
    if profile_id:
        logger.debug(
            "search_run: profile_id=%r provided but workspace_profiles not yet "
            "implemented — using empty profile",
            profile_id,
        )
    return ProfileSnapshot.empty()


def _mark_needs_review(
    env: TaskEnvelope,
    *,
    invocation_id: str | None,
    reason: str,
    error_code: str = "VALIDATOR_GATE_FAILED",
) -> None:
    """Helper: mark task and run as needs_review and append event."""
    with get_session() as session:
        task_repo = TaskRepository(session)
        run_repo = RunRepository(session)
        event_repo = TaskEventRepository(session)
        task_repo.mark_needs_review(
            env.task_id,
            error_code=error_code,
            error_message=reason[:500],
        )
        run_repo.set_status(env.run_id, "needs_review")
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_needs_review",
            message=reason,
        )
