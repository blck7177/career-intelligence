#!/usr/bin/env python3
"""
career_write_manifest — Write the agent output manifest to the designated path.

Usage:
    python career_write_manifest.py --task-spec <path> [--output <path>]

task-spec JSON must contain:
  - invocation_id, status, stop_reason
  - artifact_paths: dict of artifact_type → file path
  - summary: dict of stats
  - run_id, task_id (required when output_manifest_path is absent)
  - output_paths.output_manifest_path (preferred canonical path)

The manifest is always written to the platform-derived canonical path:
  1. AGENT_ARTIFACTS_DIR / run_id / task_id / "output_manifest.json", using the
     worker-authoritative run_id/task_id (CAREER_TRUE_RUN_ID/CAREER_TRUE_TASK_ID env
     vars, injected by the career-exec-identity-guard OpenClaw plugin) when present
  2. spec["output_paths"]["output_manifest_path"], only when that trusted identity
     is unavailable
  3. AGENT_ARTIFACTS_DIR / run_id / task_id / "output_manifest.json", from the
     agent-reported run_id/task_id, as a last resort

--output is optional and workspace-relative; it receives a small ack JSON only.
Agents must not construct manifest paths manually.

This is the LAST wrapper the agent calls before stopping.
This wrapper is in the OpenClaw exec allowlist.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from _manifest_identity import resolve_invocation_id, resolve_run_task_ids

VALID_STATUSES = {"completed", "partial", "failed"}
_DEFAULT_ARTIFACTS_DIR = "/app/data/agent_artifacts"


def resolve_manifest_output_path(
    spec: dict, run_id: str, task_id: str, trusted: bool, artifacts_dir: Path
) -> Path:
    """Derive the canonical output_manifest.json path (never from CLI, never hand-copied).

    When `trusted` is True (worker-authoritative run_id/task_id were resolved via
    resolve_run_task_ids), the path is always derived from them —
    spec["output_paths"]["output_manifest_path"] is ignored even if present, because
    that field is exactly what a confused agent can point at a different run's
    directory (see resolve_run_task_ids docstring and
    dev_note/career/phase20-launch-hardening/openclaw_http_migration_0712). Otherwise,
    falls back to the pre-existing behavior: prefer
    spec["output_paths"]["output_manifest_path"], else derive from the agent-reported
    run_id/task_id.
    """
    if trusted:
        return artifacts_dir / run_id / task_id / "output_manifest.json"

    output_paths = spec.get("output_paths") or {}
    manifest_path = output_paths.get("output_manifest_path")
    if manifest_path:
        return Path(manifest_path)

    if not run_id or not task_id:
        raise ValueError(
            "task spec must include output_paths.output_manifest_path "
            "or both run_id and task_id"
        )
    return artifacts_dir / run_id / task_id / "output_manifest.json"


@click.command()
@click.option("--task-spec", required=True, type=click.Path(exists=True))
@click.option(
    "--output",
    default="./manifest_write_result.json",
    show_default=True,
    type=click.Path(),
    help="Workspace-relative ack JSON path (manifest is not written here).",
)
def main(task_spec: str, output: str) -> None:
    spec_path = Path(task_spec)
    try:
        spec = json.loads(spec_path.read_text())
    except Exception as exc:
        _fail(output, None, f"Failed to read task spec: {exc}")
        sys.exit(1)

    artifacts_dir = Path(spec.get("artifacts_dir") or os.environ.get("AGENT_ARTIFACTS_DIR", _DEFAULT_ARTIFACTS_DIR))
    run_id, task_id, trusted_ids = resolve_run_task_ids(spec)

    try:
        manifest_output_path = resolve_manifest_output_path(spec, run_id, task_id, trusted_ids, artifacts_dir)
    except ValueError as exc:
        _fail(output, None, str(exc))
        sys.exit(1)

    status = spec.get("status", "")
    if status not in VALID_STATUSES:
        _fail(output, manifest_output_path, f"status must be one of {VALID_STATUSES}, got: {status!r}")
        sys.exit(1)

    invocation_id = resolve_invocation_id(spec, artifacts_dir)

    summary = spec.get("summary", {})

    # Promote discovery summary fields to top-level so DiscoveryManifest.model_validate()
    # can read them directly. The agent may supply them inside summary{} or at top-level;
    # top-level wins, then summary, then default.
    candidate_count = spec.get("candidate_count", summary.get("candidate_count", 0))
    sources_tried = spec.get("sources_tried", summary.get("sources_tried", []))
    sources_added = spec.get("sources_added", summary.get("sources_added", []))

    # Promote research summary fields to top-level so ResearchManifest.model_validate()
    # can read them. Same precedence rule: top-level > summary > default.
    job_id = spec.get("job_id", summary.get("job_id"))
    citations_count = spec.get("citations_count", summary.get("citations_count", 0))
    jd_text = spec.get("jd_text", summary.get("jd_text"))

    # Promote reflect summary fields to top-level so ReflectionManifest.model_validate()
    # can read them. When run_id/task_id are trusted (see resolve_run_task_ids), this
    # is this reflection task's own run_id, never the agent's self-reported value —
    # closes the run_id/reflected_run_id mixup described there.
    reflect_run_id = run_id if trusted_ids else spec.get("run_id", summary.get("run_id"))
    patches_proposed = spec.get("patches_proposed", summary.get("patches_proposed", 0))

    manifest = {
        "invocation_id": invocation_id,
        "status": status,
        "stop_reason": spec.get("stop_reason", ""),
        "artifact_paths": spec.get("artifact_paths", {}),
        "summary": summary,
        # Discovery fields
        "candidate_count": candidate_count,
        "sources_tried": sources_tried,
        "sources_added": sources_added,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }

    # Conditionally include task-type-specific top-level fields.
    # Only add when present so manifests stay clean for their task type.
    if job_id is not None:
        manifest["job_id"] = job_id
        manifest["citations_count"] = citations_count
        if jd_text is not None:
            manifest["jd_text"] = jd_text
    if reflect_run_id is not None and job_id is None:
        manifest["run_id"] = reflect_run_id
        manifest["patches_proposed"] = patches_proposed

    # Sync workspace-local artifacts to their declared artifact-volume paths.
    # The agent writes search_ledger.jsonl and coverage_report.md to the workspace
    # using relative paths, but the manifest declares absolute artifact-volume paths.
    # We copy them here so ProvenanceValidator finds the files where it expects them.
    _sync_workspace_artifacts(spec.get("artifact_paths", {}))

    # Remove artifact_paths entries where the file does not exist on disk.
    # Agents sometimes declare all output_paths in artifact_paths even if they
    # didn't write the optional files (e.g. search_ledger). ProvenanceValidator
    # checks every declared path, so phantom entries cause needless failures.
    manifest["artifact_paths"] = _filter_existing_artifacts(manifest["artifact_paths"])

    # With a trusted run_id/task_id, also drop any artifact_paths entry that
    # resolves outside this run's own directory — the same agent confusion that
    # can misdirect output_manifest_path can also point reflection_report/
    # strategy_patch absolute paths into a different run's directory (observed in
    # dev_note/career/phase20-launch-hardening/openclaw_http_migration_0712). A
    # manifest must never vouch for another run's files as its own artifacts.
    if trusted_ids:
        manifest["artifact_paths"] = _filter_foreign_artifacts(
            manifest["artifact_paths"], artifacts_dir, run_id, task_id
        )

    manifest_output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_output_path.write_text(json.dumps(manifest, indent=2))

    # Append a signed ledger event so ToolLedgerValidator can verify manifest provenance.
    signing_key = os.environ.get("TOOL_LEDGER_SIGNING_KEY", "")
    tool_events_path_str = spec.get("output_paths", {}).get("tool_events_path", "")
    if tool_events_path_str and signing_key:
        try:
            sys.path.insert(0, "/app")  # PYTHONPATH is stripped by OpenClaw exec security policy
            from packages.infrastructure.tool_ledger import append_signed_event  # noqa: PLC0415

            manifest_hash = "sha256:" + hashlib.sha256(manifest_output_path.read_bytes()).hexdigest()
            append_signed_event(
                Path(tool_events_path_str),
                {
                    "invocation_id": invocation_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "tool_name": "career_write_manifest",
                    "event_type": "manifest_write",
                    "status": "ok",
                    "candidate_count": candidate_count,
                    "output_path": str(manifest_output_path),
                    "output_hash": manifest_hash,
                },
                signing_key,
            )
        except Exception as exc:  # noqa: BLE001
            click.echo(f"WARNING: failed to append signed ledger event: {exc}", err=True)

    ack = {
        "status": "ok",
        "manifest_path": str(manifest_output_path),
        "manifest_status": status,
    }
    _write_ack_if_safe(output, manifest_output_path, ack)

    click.echo(f"Manifest written to {manifest_output_path}", err=True)


def _write_ack_if_safe(output: str, manifest_output_path: Path, ack: dict) -> None:
    """Write workspace ack JSON unless --output targets the canonical manifest path."""
    ack_path = Path(output)
    try:
        if ack_path.resolve() == manifest_output_path.resolve():
            click.echo(
                "Skipping ack write: --output equals canonical manifest path",
                err=True,
            )
            return
    except OSError:
        # Unresolvable paths (e.g. missing parent) — compare as strings as fallback.
        if str(ack_path) == str(manifest_output_path):
            click.echo(
                "Skipping ack write: --output equals canonical manifest path",
                err=True,
            )
            return
    ack_path.write_text(json.dumps(ack, indent=2))


def _filter_existing_artifacts(artifact_paths: dict) -> dict:
    """Remove entries where the declared file does not exist on disk."""
    filtered = {}
    for artifact_type, path_str in artifact_paths.items():
        if not path_str:
            continue
        if Path(path_str).exists():
            filtered[artifact_type] = path_str
        else:
            click.echo(
                f"INFO: dropping artifact_paths.{artifact_type} — "
                f"file does not exist: {path_str}",
                err=True,
            )
    return filtered


def _filter_foreign_artifacts(artifact_paths: dict, artifacts_dir: Path, run_id: str, task_id: str) -> dict:
    """Drop artifact_paths entries that resolve outside this run's own directory."""
    own_dir = (artifacts_dir / run_id / task_id).resolve()
    filtered = {}
    for artifact_type, path_str in artifact_paths.items():
        resolved = Path(path_str).resolve()
        if resolved.parent == own_dir or own_dir in resolved.parents:
            filtered[artifact_type] = path_str
        else:
            click.echo(
                f"WARNING: dropping artifact_paths.{artifact_type} — resolves "
                f"outside this run's directory ({own_dir}): {path_str}",
                err=True,
            )
    return filtered


def _sync_workspace_artifacts(artifact_paths: dict) -> None:
    """
    Copy workspace-relative artifacts to their declared artifact-volume paths.

    The agent writes files like search_ledger.jsonl and coverage_report.md using
    relative paths (./search_ledger.jsonl), which land in the OpenClaw workspace.
    ProvenanceValidator checks the absolute paths declared in the manifest. This
    function bridges the gap by copying workspace files to the artifact volume.
    """
    cwd = Path.cwd()
    for artifact_type, path_str in artifact_paths.items():
        if not path_str:
            continue
        dest = Path(path_str)
        if dest.exists():
            continue
        src = cwd / dest.name
        if src.exists():
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            except Exception as exc:  # noqa: BLE001
                click.echo(
                    f"WARNING: could not sync {artifact_type} from workspace to artifact dir: {exc}",
                    err=True,
                )


def _fail(output: str, manifest_path: Path | None, message: str) -> None:
    error_payload = {"error": message, "status": "failed"}
    if manifest_path is not None:
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(error_payload))
        except OSError:
            Path(output).write_text(json.dumps(error_payload))
    else:
        Path(output).write_text(json.dumps(error_payload))
    click.echo(f"ERROR: {message}", err=True)


if __name__ == "__main__":
    main()
