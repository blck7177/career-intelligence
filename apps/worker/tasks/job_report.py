"""
Handler for job_report tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a Job Intelligence Report for a given job record.

The report covers:
  - Role summary and responsibilities
  - Team and org signals
  - Compensation signals (if visible)
  - Culture fit signals
  - Suggested research angles

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
You are a job intelligence analyst specializing in quantitative finance and market risk roles.
Given a job record, produce a structured Job Intelligence Report.

Rules:
- Be analytical and specific; avoid filler language.
- If a field is not present in the job record, note "Not available" rather than guessing.
- Use markdown formatting with clear headings.
- Be concise: the report should fit in 600–800 words.
"""

_USER_PROMPT_TEMPLATE = """\
Produce a Job Intelligence Report for the following job:

```json
{job_json}
```

Structure the report as:
## 1. Role Summary
## 2. Key Responsibilities
## 3. Required Skills & Qualifications
## 4. Team & Org Signals
## 5. Compensation Signals
## 6. Culture & Environment Signals
## 7. Research Angles (questions worth investigating before applying)
"""


def handle_job_report(env: TaskEnvelope) -> dict:
    """
    Entry point for job_report tasks.
    Called by execute_task when task_type == "job_report".
    """
    logger.info("job_report: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    # ------------------------------------------------------------------
    # Step 1: Read input snapshot (expects job_id or job_json in payload)
    # ------------------------------------------------------------------
    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        input_snapshot = run.input_snapshot_json or {}

    job_data = input_snapshot.get("job", {})
    if not job_data:
        _mark_failed(env, error_code="MISSING_JOB_INPUT", message="No job data in input_snapshot")
        return {"status": "failed", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 2: Call LLM to generate report
    # ------------------------------------------------------------------
    job_json = json.dumps(job_data, indent=2, ensure_ascii=False)
    user_prompt = _USER_PROMPT_TEMPLATE.format(job_json=job_json)

    try:
        llm = get_llm_client()
        report_text = llm.complete_simple(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=2048,
        )
    except LLMCallError as exc:
        logger.exception("job_report: LLM call failed: %s", exc)
        _mark_failed(env, error_code="LLM_CALL_FAILED", message=str(exc)[:500])
        return {"status": "failed", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 3: Write report to artifact volume
    # ------------------------------------------------------------------
    report_dir = Path(_ARTIFACTS_DIR) / env.run_id / env.task_id
    report_dir.mkdir(parents=True, exist_ok=True)

    job_id = job_data.get("id", env.task_id)
    report_path = report_dir / f"job_report_{job_id}.md"
    report_path.write_text(report_text, encoding="utf-8")
    logger.info("job_report: report written to %s (%d chars)", report_path, len(report_text))

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
            artifact_type="job_report",
            storage_uri=str(report_path),
            metadata_json={"job_id": job_id, "char_count": len(report_text)},
        )

        task_repo.mark_succeeded(env.task_id)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=f"Job Intelligence Report generated for job_id={job_id}",
        )

    logger.info("job_report: task_id=%s succeeded", env.task_id)
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
