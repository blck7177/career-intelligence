"""
Shared helper: resolve the authoritative invocation_id for a wrapper call.

Real-data testing (2026-07-11, 5-round discovery/reflect loop test) found the
agent substituting run_id's value for invocation_id in 4/5 real runs — always
in the exact same direction (never task_id), consistent with invocation_id
being the one ID field the agent never reads back (unlike run_id/task_id,
which gate the agent's own later file reads and so get self-corrected).

The worker already writes the authoritative invocation_id into input.json at
a path fully determined by run_id + task_id, before the agent ever starts.
Trust that over whatever the agent's own spec JSON claims.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def resolve_run_task_ids(spec: dict) -> tuple[str, str, bool]:
    """
    Return the authoritative (run_id, task_id, trusted) for this wrapper invocation.

    Reads CAREER_TRUE_RUN_ID / CAREER_TRUE_TASK_ID, injected by the
    career-exec-identity-guard OpenClaw plugin's resolve_exec_env hook from
    the worker-authoritative session_key (built server-side in
    packages/domain/agent_jobs/planner.py::build_session_key, never accepted
    from the agent) — independent of anything the agent typed into its
    task-spec JSON.

    Fixes the run_reflection failure mode where the agent has two distinct
    run identities in context (its own run vs. payload.reflected_run_id, the
    discovery run being analyzed) and sometimes writes the wrong one into
    run_id/task_id/output_paths.output_manifest_path (see
    dev_note/career/phase20-launch-hardening/openclaw_http_migration_0712).

    Falls back to the agent-reported spec values when either env var is
    absent (e.g. the plugin isn't installed in this environment), so this is
    purely additive robustness — never a new hard-failure mode for the
    wrapper. `trusted` tells the caller whether the returned ids came from
    the env (True) or are just the agent's own claim (False).
    """
    agent_run_id = str(spec.get("run_id", "") or "")
    agent_task_id = str(spec.get("task_id", "") or "")

    true_run_id = os.environ.get("CAREER_TRUE_RUN_ID", "")
    true_task_id = os.environ.get("CAREER_TRUE_TASK_ID", "")

    if not true_run_id or not true_task_id:
        return agent_run_id, agent_task_id, False

    if true_run_id != agent_run_id or true_task_id != agent_task_id:
        print(
            f"INFO: correcting run_id/task_id — agent reported "
            f"({agent_run_id!r}, {agent_task_id!r}), env says "
            f"({true_run_id!r}, {true_task_id!r})",
            file=sys.stderr,
        )
    return true_run_id, true_task_id, True


def resolve_invocation_id(spec: dict, artifacts_dir: Path) -> str:
    """
    Return the authoritative invocation_id for this run/task.

    Reads it from the worker-written input.json at
    <artifacts_dir>/<run_id>/<task_id>/input.json (path is deterministic —
    computed the same way by packages/domain/agent_jobs/planner.py on the
    worker side). Falls back to the agent-reported spec value if input.json
    is missing/unreadable/malformed, so this is purely additive robustness —
    never a new hard-failure mode for the wrapper.
    """
    agent_reported = str(spec.get("invocation_id", "") or "")
    run_id = spec.get("run_id", "")
    task_id = spec.get("task_id", "")
    if not run_id or not task_id:
        return agent_reported

    input_json_path = artifacts_dir / run_id / task_id / "input.json"
    try:
        real_invocation_id = json.loads(input_json_path.read_text()).get("invocation_id", "")
    except Exception:
        return agent_reported

    if not real_invocation_id:
        return agent_reported

    if real_invocation_id != agent_reported:
        print(
            f"INFO: correcting invocation_id — agent reported {agent_reported!r}, "
            f"input.json says {real_invocation_id!r}",
            file=sys.stderr,
        )
    return real_invocation_id
