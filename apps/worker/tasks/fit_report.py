"""
Handler for fit_report tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a Candidate Fit Report for a job-profile pair.

The report assesses:
  - Skills alignment (hard and soft)
  - Experience level match
  - Domain and sector fit
  - Likely gaps to address
  - Overall fit rating (strong / partial / stretch)

The report is stored as an artifact and the task is marked succeeded.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.infrastructure.db.repositories import (
    ArtifactRepository,
    RunRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session
from packages.infrastructure.llm.client import LLMCallError, get_llm_client

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")

_SYSTEM_PROMPT = """\
You are a career fit analyst specializing in quantitative finance and market risk.
Given a candidate profile and a job record, produce a Candidate Fit Report.

Rules:
- Be specific about skill alignment and gaps; avoid vague language.
- Use evidence from both profile and job posting.
- Rate overall fit: Strong Fit / Partial Fit / Stretch.
- Be concise: 500–700 words.
"""

_USER_PROMPT_TEMPLATE = """\
Produce a Candidate Fit Report.

Candidate profile:
```json
{profile_json}
```

Job posting:
```json
{job_json}
```

Structure the report as:
## 1. Skills Alignment (Hard Skills)
## 2. Skills Alignment (Soft Skills & Domain)
## 3. Experience Level Match
## 4. Key Gaps to Address
## 5. Overall Fit Rating
## 6. Application Strategy Notes
"""


def handle_fit_report(env: TaskEnvelope) -> dict:
    """
    Entry point for fit_report tasks.
    Called by execute_task when task_type == "fit_report".
    """
    logger.info("fit_report: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    # ------------------------------------------------------------------
    # Step 1: Read input snapshot (expects job + profile in payload)
    # ------------------------------------------------------------------
    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        input_snapshot = run.input_snapshot_json or {}

    job_data = input_snapshot.get("job", {})
    profile_data = input_snapshot.get("profile", {})

    if not job_data or not profile_data:
        missing = []
        if not job_data:
            missing.append("job")
        if not profile_data:
            missing.append("profile")
        _mark_failed(
            env,
            error_code="MISSING_FIT_INPUT",
            message=f"Missing required fields in input_snapshot: {missing}",
        )
        return {"status": "failed", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 2: Call LLM to generate fit report
    # ------------------------------------------------------------------
    job_json = json.dumps(job_data, indent=2, ensure_ascii=False)
    profile_json = json.dumps(profile_data, indent=2, ensure_ascii=False)
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        profile_json=profile_json,
        job_json=job_json,
    )

    try:
        llm = get_llm_client()
        report_text = llm.complete_simple(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=2048,
        )
    except LLMCallError as exc:
        logger.exception("fit_report: LLM call failed: %s", exc)
        _mark_failed(env, error_code="LLM_CALL_FAILED", message=str(exc)[:500])
        return {"status": "failed", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 3: Write report to artifact volume
    # ------------------------------------------------------------------
    report_dir = Path(_ARTIFACTS_DIR) / env.run_id / env.task_id
    report_dir.mkdir(parents=True, exist_ok=True)

    job_id = job_data.get("id", "unknown")
    report_path = report_dir / f"fit_report_{job_id}.md"
    report_path.write_text(report_text, encoding="utf-8")
    logger.info("fit_report: report written to %s (%d chars)", report_path, len(report_text))

    # ------------------------------------------------------------------
    # Step 4: Write artifact record and mark task succeeded
    # ------------------------------------------------------------------
    with get_session() as session:
        artifact_repo = ArtifactRepository(session)
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)

        artifact_repo.create(
            run_id=env.run_id,
            task_id=env.task_id,
            artifact_type="fit_report",
            storage_uri=str(report_path),
            metadata_json={"job_id": job_id, "char_count": len(report_text)},
        )

        task_repo.mark_succeeded(env.task_id)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=f"Candidate Fit Report generated for job_id={job_id}",
        )

    logger.info("fit_report: task_id=%s succeeded", env.task_id)
    return {"status": "succeeded", "task_id": env.task_id, "job_id": job_id}


def _mark_failed(env: TaskEnvelope, *, error_code: str, message: str) -> None:
    with get_session() as session:
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        task_repo.mark_failed(
            env.task_id,
            error_code=error_code,
            error_message=message,
        )
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_failed",
            message=message,
        )
