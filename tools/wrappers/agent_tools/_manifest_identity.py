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
import sys
from pathlib import Path


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
