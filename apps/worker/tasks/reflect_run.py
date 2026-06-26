"""
Handler for agent.run_reflection tasks.

Execution mode: OPENCLAW
Agent: career-reflect-agent
Skill: career-reflect-operator

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

Note: strategy_patch.json is written as an artifact. After validator pass the worker
best-effort applies the patch via apply_strategy_patch() into search_strategy_states.
Invalid patches are rejected without failing the reflect run.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from packages.contracts.agents.invocation import AgentBudget
from packages.contracts.agents.manifests import ReflectionManifest
from packages.contracts.api.runs import RunReflectionInput
from packages.contracts.strategy.reflection import ReflectionTaskPayload
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.domain.agent_jobs.planner import build_invocation_spec, build_task_input
from packages.domain.strategy_state import (
    StrategyPatchError,
    apply_strategy_patch,
    validate_strategy_patch,
)
from packages.infrastructure.agent_runtime.openclaw import create_runtime
from packages.infrastructure.agent_runtime.validator import ValidatorGate
from packages.infrastructure.db.repositories import (
    AgentInvocationRepository,
    AgentValidationResultRepository,
    ArtifactRepository,
    RunRepository,
    SearchStrategyStateRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")


def handle_reflect_run(env: TaskEnvelope) -> dict:
    """
    Entry point for agent.run_reflection tasks.
    Called by execute_task when task_type == "agent.run_reflection".
    """
    logger.info("reflect_run: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    # ------------------------------------------------------------------
    # Step 1: Read run context from Postgres
    # ------------------------------------------------------------------
    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        input_snapshot = run.input_snapshot_json or {}
        workspace_id = env.workspace_id

    try:
        inp = RunReflectionInput.model_validate(input_snapshot)
    except ValidationError as exc:
        logger.error("reflect_run: invalid input_snapshot: %s", exc)
        _mark_needs_review(
            env,
            invocation_id="",
            reason=f"Invalid run_reflection input_snapshot: {exc}",
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
    # Step 3: Build enriched input.json and write to artifact volume
    # ------------------------------------------------------------------
    with get_session() as session:
        reflection_payload = _build_reflection_payload(
            session,
            workspace_id=workspace_id,
            inp=inp,
        )

    task_input = build_task_input(
        spec=spec,
        task_type=env.task_type,
        payload=reflection_payload.model_dump(mode="json"),
        budget=budget,
    )

    run_dir = Path(_ARTIFACTS_DIR) / env.run_id / env.task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    input_json_path = Path(spec.input_spec_path)
    input_json_path.write_text(task_input.model_dump_json(indent=2))
    logger.info("reflect_run: wrote input.json to %s", input_json_path)

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
            "reflect_run: output_manifest.json not found at %s", manifest_path
        )
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason="output_manifest.json not found after agent completion",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    try:
        raw = json.loads(manifest_path.read_text())
        manifest = ReflectionManifest.model_validate(raw)
    except Exception as exc:
        logger.exception("reflect_run: failed to parse output_manifest.json: %s", exc)
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason=f"output_manifest.json parse error: {exc}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

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
            "reflect_run: validator gate FAILED for task %s: %s",
            env.task_id,
            failed_validators,
        )
        _mark_needs_review(
            env,
            invocation_id=invocation_id,
            reason=f"Validator gate failed: {failed_validators}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    reflected_run_id = inp.run_id

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
                metadata_json={
                    "invocation_id": invocation_id,
                    "reflected_run_id": reflected_run_id,
                },
            )

        _best_effort_apply_strategy_patch(
            session,
            env=env,
            manifest=manifest,
            workspace_id=workspace_id,
            reflected_run_id=reflected_run_id,
            event_repo=event_repo,
        )

        task_repo.mark_succeeded(env.task_id)
        run_repo.complete(
            env.run_id,
            status="succeeded",
            result_summary={
                "reflected_run_id": reflected_run_id,
                "patches_proposed": manifest.patches_proposed,
                "invocation_id": invocation_id,
            },
        )
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=(
                f"Reflection complete: run_id={reflected_run_id}, "
                f"patches_proposed={manifest.patches_proposed}"
            ),
        )

    logger.info(
        "reflect_run: task_id=%s succeeded, reflected_run=%s patches=%d",
        env.task_id,
        reflected_run_id,
        manifest.patches_proposed,
    )
    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "reflected_run_id": reflected_run_id,
        "patches_proposed": manifest.patches_proposed,
    }


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
            result_summary={
                "validation_status": "failed",
                "error_code": error_code,
                "invocation_id": invocation_id,
            },
        )
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_needs_review",
            message=reason,
        )


def _build_reflection_payload(session, *, workspace_id: str, inp: RunReflectionInput) -> ReflectionTaskPayload:
    """Enrich reflect agent input with artifact paths and current strategy state."""
    artifact_repo = ArtifactRepository(session)
    run_repo = RunRepository(session)
    strategy_repo = SearchStrategyStateRepository(session)

    reflected_run_id = inp.run_id
    artifacts = artifact_repo.list_for_run(reflected_run_id)
    paths = {a.artifact_type: a.storage_uri for a in artifacts}

    reflected_summary: dict = {}
    try:
        reflected_run = run_repo.get_or_raise(reflected_run_id)
        reflected_summary = reflected_run.result_summary_json or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "reflect_run: could not load reflected run summary for %s: %s",
            reflected_run_id,
            exc,
        )

    current_state = strategy_repo.get_for_workspace(workspace_id)

    return ReflectionTaskPayload(
        reflected_run_id=reflected_run_id,
        max_tool_calls=inp.max_tool_calls,
        timeout_seconds=inp.timeout_seconds,
        coverage_report_path=paths.get("coverage_report"),
        search_ledger_path=paths.get("search_ledger"),
        candidate_pool_path=paths.get("candidate_pool"),
        reflected_run_summary=reflected_summary,
        current_strategy_state=current_state,
    )


def _best_effort_apply_strategy_patch(
    session,
    *,
    env: TaskEnvelope,
    manifest: ReflectionManifest,
    workspace_id: str,
    reflected_run_id: str,
    event_repo: TaskEventRepository,
) -> None:
    """Validate and apply strategy_patch.json; never fail the reflect run."""
    patch_path_str = manifest.artifact_paths.get("strategy_patch")
    if not patch_path_str:
        logger.info("reflect_run: no strategy_patch artifact — skipping apply")
        return

    patch_path = Path(patch_path_str)
    if not patch_path.exists():
        logger.warning("reflect_run: strategy_patch missing at %s — skipping apply", patch_path)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="strategy_patch_rejected",
            message="strategy_patch file not found on disk",
        )
        return

    try:
        raw = json.loads(patch_path.read_text(encoding="utf-8"))
        patch = validate_strategy_patch(raw)
    except (json.JSONDecodeError, StrategyPatchError) as exc:
        logger.warning("reflect_run: strategy patch rejected: %s", exc)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="strategy_patch_rejected",
            message=str(exc)[:500],
        )
        return

    strategy_repo = SearchStrategyStateRepository(session)
    current = strategy_repo.get_for_workspace(workspace_id)
    new_state = apply_strategy_patch(
        current,
        patch,
        workspace_id=workspace_id,
        reflection_run_id=env.run_id,
        reflection_task_id=env.task_id,
    )
    strategy_repo.upsert(new_state)
    event_repo.append(
        task_id=env.task_id,
        run_id=env.run_id,
        event_type="strategy_patch_applied",
        message=f"Strategy patch applied for reflected_run={reflected_run_id}",
        payload_json=new_state.model_dump(mode="json"),
    )
    logger.info(
        "reflect_run: strategy patch applied workspace=%s reflected_run=%s",
        workspace_id,
        reflected_run_id,
    )
