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
  10. Pass → write artifacts to DB, persist result_summary_json, mark task succeeded
  11. Fail → mark task needs_review, no artifact writes
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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
from packages.domain.strategy_state import materialize_discovery_hints
from packages.infrastructure.agent_runtime.openclaw import create_runtime
from packages.infrastructure.agent_runtime.validator import ValidatorGate
from packages.infrastructure.db.repositories import (
    AgentInvocationRepository,
    AgentToolEventRepository,
    AgentValidationResultRepository,
    ArtifactRepository,
    JobRepository,
    ProfileRepository,
    RunRepository,
    SearchStrategyStateRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session
from packages.infrastructure.llm.client import get_llm_client
from packages.infrastructure.jd_fetch import resolve_jd
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
            phase="input_validation",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 1c: Load ProfileSnapshot from DB (falls back to empty if none)
    # ------------------------------------------------------------------
    profile_snapshot = _load_profile(workspace_id=workspace_id)

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
            phase="input_validation",
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
            phase="intent_translation",
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

    # Generate a single UUID that will be used as both spec.invocation_id and
    # the agent_invocations DB row id.  This ensures tool_events.jsonl events
    # (written with spec.invocation_id) can be matched during _ingest_tool_events
    # and stored in agent_tool_events with a correct FK to agent_invocations.
    import uuid as _uuid
    unified_invocation_id = str(_uuid.uuid4())

    spec = build_invocation_spec(
        run_id=env.run_id,
        task_id=env.task_id,
        workspace_id=workspace_id,
        task_type=env.task_type,
        attempt=env.attempt,
        artifacts_base_dir=_ARTIFACTS_DIR,
        payload={},  # payload is built separately below via DiscoveryTaskSpec
        budget=budget,
        invocation_id=unified_invocation_id,
    )

    # ------------------------------------------------------------------
    # Step 3: Build DiscoveryTaskSpec and write to input.json
    # ------------------------------------------------------------------
    with get_session() as session:
        strategy_state = SearchStrategyStateRepository(session).get_for_workspace(workspace_id)

    source_registry_snapshot = None
    previous_run_diagnostics = None
    if strategy_state is not None:
        source_registry_snapshot, previous_run_diagnostics = materialize_discovery_hints(
            strategy_state
        )
        logger.info(
            "search_run: loaded strategy state for workspace=%s "
            "(known_boards=%d, coverage_gaps=%d, recommended=%d)",
            workspace_id,
            len(source_registry_snapshot.known_boards),
            len(previous_run_diagnostics.coverage_gaps),
            len(previous_run_diagnostics.recommended_next_searches),
        )

    task_spec = build_discovery_task_spec(
        discovery_intent=discovery_intent,
        search_depth=frontend_input.search_depth,
        artifacts_dir=_ARTIFACTS_DIR,
        run_id=env.run_id,
        task_id=env.task_id,
        source_registry_snapshot=source_registry_snapshot,
        previous_run_diagnostics=previous_run_diagnostics,
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
    _prepare_agent_run_dir(run_dir)

    input_json_path = Path(spec.input_spec_path)
    input_json_path.write_text(task_input.model_dump_json(indent=2))
    # Ensure gateway (uid=1000) can read input.json written by this process.
    _fix_file_perms(input_json_path)
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
            phase="agent_invocation",
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
            error_code="MANIFEST_NOT_FOUND",
            phase="manifest_read",
            result_summary_extra={
                "artifact_paths": {
                    "output_manifest_path": task_spec.output_paths.output_manifest_path,
                }
            },
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
            error_code="MANIFEST_PARSE_ERROR",
            phase="manifest_read",
            result_summary_extra={
                "artifact_paths": {
                    "output_manifest_path": task_spec.output_paths.output_manifest_path,
                }
            },
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 7.5a: Canonicalize artifact_paths from task_spec.output_paths
    # ------------------------------------------------------------------
    # The agent must not be trusted to construct platform-side file paths.
    # Overwrite artifact_paths with the deterministic paths built by the
    # planner from run_id + task_id — the single authoritative source.
    _canonicalize_discovery_artifact_paths(
        manifest,
        task_spec.output_paths,
        manifest_path,
    )

    # ------------------------------------------------------------------
    # Step 7.5b: Normalize candidate_pool content format
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
            phase="validator_gate",
            result_summary_extra={
                "failed_validators": [
                    {
                        "name": r.validator_name,
                        "errors": [e.model_dump() for e in r.errors],
                    }
                    for r in validation_results
                    if r.status == "failed"
                ],
                "candidate_count": manifest.candidate_count,
                "artifact_paths": {
                    "output_manifest_path": task_spec.output_paths.output_manifest_path,
                    "tool_events_path": task_spec.output_paths.tool_events_path,
                },
            },
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 10a: Ingest signed tool events into Postgres
    # ------------------------------------------------------------------
    _ingest_tool_events(task_spec, invocation_id)

    # ------------------------------------------------------------------
    # Step 10b: Persist discovered jobs to jobs table
    # ------------------------------------------------------------------
    ingest_stats = _persist_discovered_jobs(manifest, env.run_id, env.task_id)
    job_ids = ingest_stats["job_ids"]

    with get_session() as session:
        artifact_repo = ArtifactRepository(session)
        task_repo = TaskRepository(session)
        run_repo = RunRepository(session)
        event_repo = TaskEventRepository(session)

        artifact_ids: list[str] = []
        for artifact_type, path_str in manifest.artifact_paths.items():
            artifact = artifact_repo.create(
                run_id=env.run_id,
                task_id=env.task_id,
                artifact_type=artifact_type,
                storage_uri=path_str,
                content_hash=_compute_file_sha256(path_str),
                metadata_json={"invocation_id": invocation_id},
            )
            artifact_ids.append(artifact.id)

        result_summary = {
            "candidate_count": manifest.candidate_count,
            "job_ids": job_ids,
            "jobs_ingested": ingest_stats["jobs_ingested"],
            "jobs_reportable": ingest_stats["jobs_reportable"],
            "jobs_fetch_failed": ingest_stats["jobs_fetch_failed"],
            "artifact_ids": artifact_ids,
            "invocation_id": invocation_id,
            "sources_tried": len(manifest.sources_tried),
            "validation_status": "passed",
        }

        task_repo.mark_succeeded(env.task_id)
        run_repo.complete(env.run_id, status="succeeded", result_summary=result_summary)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=(
                f"Discovery complete: {manifest.candidate_count} candidates, "
                f"{len(manifest.sources_tried)} sources tried, "
                f"{len(job_ids)} jobs persisted to database"
            ),
        )

    logger.info(
        "search_run: task_id=%s succeeded, candidates=%d, jobs_persisted=%d",
        env.task_id,
        manifest.candidate_count,
        len(job_ids),
    )
    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "candidate_count": manifest.candidate_count,
        "jobs_persisted": len(job_ids),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Artifact writer identity — must match openclaw-gateway's node user (uid=1000).
# All containers that write to the shared agent_artifacts volume run as this UID.
_ARTIFACT_UID = 1000
_ARTIFACT_GID = 1000


def _prepare_agent_run_dir(run_dir: Path) -> None:
    """
    Create the run/task artifact directory and fix ownership so openclaw-gateway
    (uid=1000/node) can write output artifacts into it.

    This is a defensive shim: with unified UID across all writer containers the
    chown calls are no-ops.  If a container ever runs as root, this corrects the
    directory before OpenClaw is invoked.
    """
    import os

    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chown(run_dir, _ARTIFACT_UID, _ARTIFACT_GID)
        os.chown(run_dir.parent, _ARTIFACT_UID, _ARTIFACT_GID)
        # 775: owner+group can read/write/execute; others read+execute only.
        run_dir.chmod(0o775)
        run_dir.parent.chmod(0o755)
    except PermissionError:
        # Already running as uid=1000 — chown to same uid is a no-op on Linux
        # but raises PermissionError on strict kernels. Safe to ignore.
        logger.debug("search_run: chown skipped (already correct user)")


def _fix_file_perms(path: Path) -> None:
    """Set 664 on a file so both owner and group (1000:1000) can read/write it."""
    import os

    try:
        os.chown(path, _ARTIFACT_UID, _ARTIFACT_GID)
        path.chmod(0o664)
    except PermissionError:
        logger.debug("search_run: file chown skipped for %s", path)


def _canonicalize_discovery_artifact_paths(
    manifest: DiscoveryManifest,
    output_paths,
    manifest_path: Path,
) -> None:
    """
    Overwrite manifest.artifact_paths with paths derived from task_spec.output_paths.

    Rationale: artifact_paths in the manifest are platform-managed paths
    (run_id/task_id/filename).  The single authoritative source is the planner's
    OutputPaths object built from run_id + task_id.  Agents must not be trusted
    to construct these paths correctly.

    Only overwrites keys that are present in output_paths; does not remove keys
    the agent added for other artifact types.  Writes the corrected manifest back
    to disk so downstream readers (e.g. artifact_repo.create) also see the right
    paths.

    Also strips any platform-owned keys the agent should never declare
    (e.g. tool_events) — prevents agents from claiming ownership of
    platform-managed artifacts.
    """
    # Keys the agent is allowed to report; overwritten with platform-canonical paths.
    canonical: dict[str, str] = {
        "candidate_pool": output_paths.candidate_pool_path,
        "search_ledger": output_paths.search_ledger_path,
        "trace_events": output_paths.trace_events_path,
        "coverage_report": output_paths.coverage_report_path,
    }

    # Keys that are platform-managed and must never appear in agent-reported manifest.
    _PLATFORM_ONLY_KEYS = {"tool_events"}

    changed = False

    for key in _PLATFORM_ONLY_KEYS:
        if key in manifest.artifact_paths:
            logger.warning(
                "search_run: agent claimed platform-owned artifact key %r — removing from manifest",
                key,
            )
            del manifest.artifact_paths[key]
            changed = True

    for artifact_type, canonical_path in canonical.items():
        old_path = manifest.artifact_paths.get(artifact_type)
        if old_path != canonical_path:
            logger.warning(
                "search_run: canonicalized artifact path %s: %r → %r",
                artifact_type,
                old_path,
                canonical_path,
            )
            manifest.artifact_paths[artifact_type] = canonical_path
            changed = True

    if changed:
        manifest_path.write_text(manifest.model_dump_json(indent=2))
        _fix_file_perms(manifest_path)
        logger.info(
            "search_run: manifest artifact_paths canonicalized and written back to %s",
            manifest_path,
        )


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
        elif not pool_path.exists() and manifest.candidate_count == 0:
            # Path was declared in the manifest but the file was never written
            # (e.g. agent tried to write an empty file and the runtime rejected it).
            # Create an empty file so ProvenanceValidator finds a real artifact.
            pool_path.parent.mkdir(parents=True, exist_ok=True)
            pool_path.touch()
            logger.info(
                "search_run: candidate_pool declared in manifest but missing on disk "
                "(zero-candidate run); created empty file at %s",
                pool_path,
            )
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


def _load_profile(workspace_id: str) -> ProfileSnapshot:
    """
    Load a ProfileSnapshot from the candidate_profiles table for the given workspace.
    Returns ProfileSnapshot.empty() if no profile has been created yet.
    """
    with get_session() as session:
        row = ProfileRepository(session).get_for_workspace(workspace_id)
        if row is None:
            logger.debug(
                "search_run: no profile found for workspace %s — using empty profile",
                workspace_id,
            )
            return ProfileSnapshot.empty()

        snapshot = ProfileSnapshot(
            profile_id=row.id,
            summary=row.summary,
            experience_summary=row.experience_summary,
            education_summary=row.education_summary,
            technical_skills=row.technical_skills or [],
            subject_areas=row.subject_areas or [],
            years_of_experience=row.years_experience,       # DB column renamed: years_experience
        )
        logger.debug(
            "search_run: loaded profile %s for workspace %s (is_empty=%s)",
            row.id,
            workspace_id,
            snapshot.is_empty,
        )
        return snapshot


def _persist_discovered_jobs(
    manifest: DiscoveryManifest,
    run_id: str,
    task_id: str,
) -> dict[str, int | list[str]]:
    """
    Upsert candidates from candidate_pool.jsonl into the jobs table.

    Called after the validator gate passes so only validated candidates
    are persisted.  For each new candidate, resolve JD via artifact cache
    (career_fetch_source) or worker deterministic fetch.  Successful fetch
    → status=reportable with jd_text/jd_hash; failure → status=discovered
    with fetch_error in raw_payload_json.

    Already-known URLs are skipped (canonical_url is unique).

    Returns ingest stats including job_ids list.
    Errors are logged as warnings and do not block task completion.
    """
    empty_stats: dict[str, int | list[str]] = {
        "job_ids": [],
        "jobs_ingested": 0,
        "jobs_reportable": 0,
        "jobs_fetch_failed": 0,
    }

    pool_path_str = manifest.artifact_paths.get("candidate_pool")
    if not pool_path_str or manifest.candidate_count == 0:
        return empty_stats

    pool_path = Path(pool_path_str)
    if not pool_path.exists():
        logger.warning(
            "search_run: candidate_pool not found at %s — skipping job persistence",
            pool_path,
        )
        return empty_stats

    artifact_dir = pool_path.parent
    job_ids: list[str] = []
    new_count = 0
    skip_count = 0
    reportable_count = 0
    fetch_failed_count = 0

    try:
        with get_session() as session:
            job_repo = JobRepository(session)
            for line in pool_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("search_run: skipping malformed candidate_pool line: %s", exc)
                    continue

                url = entry.get("url", "").strip()
                if not url:
                    continue

                existing = job_repo.get_by_canonical_url(url)
                if existing:
                    job_ids.append(existing.id)
                    skip_count += 1
                    continue

                raw_source_type = entry.get("source_type", "unknown")
                norm_source_type, norm_provider = _normalize_source_type(raw_source_type)
                jd_result = resolve_jd(url, raw_source_type, artifact_dir)

                if jd_result.ok and jd_result.jd_text and jd_result.jd_hash:
                    payload = dict(entry)
                    job = job_repo.create(
                        canonical_url=url,
                        source_url=url,
                        source_type=norm_source_type,
                        source_provider=norm_provider,
                        title=entry.get("title", ""),
                        company=entry.get("company", ""),
                        location=entry.get("location") or _extract_location_from_url(url),
                        jd_text=jd_result.jd_text,
                        jd_hash=jd_result.jd_hash,
                        raw_payload_json={
                            **payload,
                            "jd_source": jd_result.source,
                            "fetch_status": jd_result.fetch_status,
                        },
                        status="reportable",
                        discovered_run_id=run_id,
                        discovered_task_id=task_id,
                    )
                    reportable_count += 1
                else:
                    fetch_failed_count += 1
                    payload = {
                        **entry,
                        "fetch_error": jd_result.error or "JD fetch failed",
                        "fetch_status": jd_result.fetch_status,
                        "jd_source": jd_result.source,
                    }
                    job = job_repo.create(
                        canonical_url=url,
                        source_url=url,
                        source_type=norm_source_type,
                        source_provider=norm_provider,
                        title=entry.get("title", ""),
                        company=entry.get("company", ""),
                        location=entry.get("location") or _extract_location_from_url(url),
                        raw_payload_json=payload,
                        status="discovered",
                        discovered_run_id=run_id,
                        discovered_task_id=task_id,
                    )
                    logger.info(
                        "search_run: JD fetch failed for url=%s error=%s",
                        url,
                        jd_result.error,
                    )

                job_ids.append(job.id)
                new_count += 1

            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_run: failed to persist discovered jobs (non-blocking): %s", exc)
        return {
            "job_ids": job_ids,
            "jobs_ingested": new_count,
            "jobs_reportable": reportable_count,
            "jobs_fetch_failed": fetch_failed_count,
        }

    logger.info(
        "search_run: jobs persisted — new=%d, reportable=%d, fetch_failed=%d, "
        "already_known=%d, total=%d",
        new_count,
        reportable_count,
        fetch_failed_count,
        skip_count,
        len(job_ids),
    )
    return {
        "job_ids": job_ids,
        "jobs_ingested": new_count,
        "jobs_reportable": reportable_count,
        "jobs_fetch_failed": fetch_failed_count,
    }


def _ingest_tool_events(task_spec, invocation_id: str) -> None:
    """
    Load verified tool events from the signed ledger and persist them to
    agent_tool_events in Postgres.

    Called after the validator gate passes so we only ingest events from
    runs that passed all checks.  Errors are logged as warnings — a failure
    here must not block task completion.
    """
    signing_key = os.environ.get("TOOL_LEDGER_SIGNING_KEY", "")
    if not signing_key:
        logger.warning(
            "search_run: TOOL_LEDGER_SIGNING_KEY not set — skipping tool event ingestion"
        )
        return

    ledger_path = Path(task_spec.output_paths.tool_events_path)
    if not ledger_path.exists():
        logger.info(
            "search_run: tool_events.jsonl not found at %s — no events to ingest", ledger_path
        )
        return

    try:
        from packages.infrastructure.tool_ledger import load_and_verify  # noqa: PLC0415

        events, errors = load_and_verify(ledger_path, invocation_id, signing_key)
        if errors:
            logger.warning(
                "search_run: tool ledger verification errors during ingestion (non-blocking): %s",
                errors,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_run: failed to load tool ledger for ingestion: %s", exc)
        return

    if not events:
        return

    try:
        with get_session() as session:
            tool_event_repo = AgentToolEventRepository(session)
            for ev in events:
                tool_event_repo.append(
                    invocation_id=invocation_id,
                    tool_name=ev.tool_name,
                    action=ev.event_type,
                    input_hash=None,
                    output_hash=ev.output_hash,
                    status=ev.status,
                    event_id=ev.event_id,
                    sequence=ev.sequence,
                    prev_event_hash=ev.prev_event_hash,
                    event_hash=ev.event_hash,
                    signature=ev.signature,
                    raw_event_json=ev.model_dump(),
                )
        logger.info(
            "search_run: ingested %d tool events for invocation %s",
            len(events),
            invocation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_run: failed to persist tool events (non-blocking): %s", exc)


def _compute_file_sha256(path_str: str) -> str | None:
    """Return sha256:<hex> for the file at path_str, or None if unreadable."""
    try:
        digest = hashlib.sha256(Path(path_str).read_bytes()).hexdigest()
        return f"sha256:{digest}"
    except OSError:
        return None


def _normalize_source_type(raw: str) -> tuple[str, Optional[str]]:
    """Map agent-supplied source_type via configs/source_registry.yaml."""
    from packages.domain.agent_jobs.source_registry import normalize_source_type

    return normalize_source_type(raw)


# City/region slug → canonical display name.
# Used as a URL-based fallback when the agent does not provide an explicit location.
_CITY_SLUG_MAP: dict[str, str] = {
    "new-york": "New York, NY",
    "jersey-city": "Jersey City, NJ",
    "san-francisco": "San Francisco, CA",
    "chicago": "Chicago, IL",
    "boston": "Boston, MA",
    "los-angeles": "Los Angeles, CA",
    "houston": "Houston, TX",
    "london": "London, UK",
    "hong-kong": "Hong Kong",
    "singapore": "Singapore",
    "tokyo": "Tokyo, Japan",
    "north-america": "North America",
    "remote": "Remote",
}


def _extract_location_from_url(url: str) -> str | None:
    """
    Best-effort extraction of a city / region from an ATS URL.

    Matches slugified city names in URL path segments (e.g. '/new-york/',
    'new-york-new-york', 'site:careers.../new-york').  Returns the canonical
    display name or None when no known city is found.
    """
    try:
        url_lower = url.lower()
        for slug, display in _CITY_SLUG_MAP.items():
            if re.search(rf"(?:^|[/\-_])({re.escape(slug)})(?:[/\-_]|$)", url_lower):
                return display
    except Exception:  # noqa: BLE001
        pass
    return None


def _mark_needs_review(
    env: TaskEnvelope,
    *,
    invocation_id: str | None,
    reason: str,
    error_code: str = "VALIDATOR_GATE_FAILED",
    phase: str = "unknown",
    result_summary_extra: dict | None = None,
) -> None:
    """
    Mark task and run as needs_review, append a task event, and write a
    structured result_summary_json so the UI can surface diagnostics without
    cross-querying task_events / agent_validation_results / artifact files.

    phase:  which execution stage failed (input_validation, intent_translation,
            agent_invocation, manifest_read, validator_gate).
    result_summary_extra:  caller-provided fields merged into the base summary
            (e.g. failed_validators, candidate_count, artifact_paths).
    """
    result_summary: dict = {
        "validation_status": "failed",
        "phase": phase,
        "error_code": error_code,
        "invocation_id": invocation_id,
    }
    if result_summary_extra:
        result_summary.update(result_summary_extra)

    with get_session() as session:
        task_repo = TaskRepository(session)
        run_repo = RunRepository(session)
        event_repo = TaskEventRepository(session)
        task_repo.mark_needs_review(
            env.task_id,
            error_code=error_code,
            error_message=reason[:500],
        )
        run_repo.complete(env.run_id, status="needs_review", result_summary=result_summary)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_needs_review",
            message=reason,
        )
