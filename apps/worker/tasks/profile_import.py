"""
Handler for profile_import tasks.

Execution mode: DETERMINISTIC
Purpose: Parse resume text into a CandidateProfile-compatible draft via LLM.

Input (from run.input_snapshot_json):
  { "resume_text": str, "source_type": "paste" }

Output:
  - run.result_summary_json populated with profile_draft + parse_notes
  - task marked succeeded
  - NO direct write to candidate_profiles — user reviews the draft on the
    frontend and saves via PUT /api/app/profile when ready
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from packages.contracts.api.profile_import import ProfileImportDraft
from packages.contracts.api.runs import ProfileImportInput
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.infrastructure.db.repositories import (
    RunRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session
from packages.infrastructure.llm.client import LLMCallError, get_llm_client

logger = logging.getLogger(__name__)

_MAX_RESUME_LENGTH = 50_000

_SYSTEM_PROMPT = """\
You are converting a resume into two outputs: a faithful resume reconstruction \
and a synthesized candidate profile for job search.

## clean_resume (faithful reconstruction)

- clean_resume.markdown: reconstruct the full resume as clean markdown, \
preserving original section order, dates, locations, and bullet points verbatim. \
Do not summarize or compress.
- clean_resume.experiences: list of dicts, each with keys like employer, title, \
location, start_date, end_date, bullets. Preserve raw strings from the resume.
- clean_resume.education: list of dicts, each with keys like institution, degree, \
graduation_date, coursework.
- clean_resume.skills: list of dicts, each with keys like category, items. \
Group by original resume categories if present.

## Profile fields (synthesized for job search)

Rules:
- Extract only facts present in the resume. Do not invent employers, degrees, \
dates, certifications, locations, or tools.
- You may synthesize a broader experience narrative from bullet points, but \
every claim must be grounded in the resume text.
- For technical_skills, subject_areas, and tools: only \
include items explicitly mentioned or strongly implied by the resume.
- For representative_projects: restructure notable accomplishments into \
title / description / skills_used / quantified_impact format.
- When unsure about an extraction, place the item in parse_notes fields \
instead of the profile fields.
- summary should be a 2-4 sentence professional headline.
- experience_summary should be an expanded multi-paragraph narrative of work \
history, synthesized from the resume.
- Return only valid JSON matching the required schema.
"""


def handle_profile_import(env: TaskEnvelope) -> dict:
    """
    Entry point for profile_import tasks.
    Called by execute_task when task_type == "profile_import".
    """
    from packages.infrastructure.llm.usage_writer import set_llm_context
    set_llm_context(run_id=env.run_id, task_id=env.task_id,
                    workspace_id=env.workspace_id, call_site="profile_import")

    logger.info("profile_import: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        snap = run.input_snapshot_json or {}

    try:
        inp = ProfileImportInput.model_validate(snap)
    except ValidationError as exc:
        logger.error("profile_import: invalid input_snapshot: %s", exc)
        _mark_failed(
            env,
            error_code="INVALID_INPUT",
            message=f"Invalid profile_import input_snapshot: {exc}",
        )
        return {"status": "failed", "task_id": env.task_id}

    resume_text = inp.resume_text.strip()

    if not resume_text:
        _mark_failed(
            env,
            error_code="MISSING_RESUME_TEXT",
            message="resume_text is required in input_snapshot",
        )
        return {"status": "failed", "task_id": env.task_id}

    if len(resume_text) > _MAX_RESUME_LENGTH:
        _mark_failed(
            env,
            error_code="RESUME_TOO_LONG",
            message=f"resume_text exceeds {_MAX_RESUME_LENGTH} character limit",
        )
        return {"status": "failed", "task_id": env.task_id}

    try:
        llm = get_llm_client()
        draft = llm.complete_structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=f"<resume_text>\n{resume_text}\n</resume_text>",
            response_schema=ProfileImportDraft,
            max_tokens=8192,
            temperature=0.2,
        )
    except LLMCallError as exc:
        logger.exception("profile_import: LLM call failed: %s", exc)
        _mark_failed(env, error_code="GENERATION_FAILED", message=str(exc)[:500])
        return {"status": "failed", "task_id": env.task_id}

    source_resume = {
        "source_type": inp.source_type,
        "raw_text": resume_text,
        "char_count": len(resume_text),
    }
    clean_resume = draft.clean_resume.model_dump()
    parse_notes = draft.parse_notes.model_dump()
    profile_fields = draft.model_dump(exclude={"parse_notes", "clean_resume"})

    with get_session() as session:
        run_repo = RunRepository(session)
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)

        run_repo.complete(env.run_id, status="succeeded", result_summary={
            "validation_status": "passed",
            "import_type": "profile_import",
            "source_resume": source_resume,
            "clean_resume": clean_resume,
            "profile_draft": profile_fields,
            "parse_notes": parse_notes,
        })
        task_repo.mark_succeeded(env.task_id)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message="Profile draft generated from resume",
        )

    logger.info("profile_import: task_id=%s succeeded", env.task_id)
    return {"status": "succeeded", "task_id": env.task_id}


def _mark_failed(env: TaskEnvelope, *, error_code: str, message: str) -> None:
    with get_session() as session:
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        run_repo = RunRepository(session)
        task_repo.mark_failed(env.task_id, error_code=error_code, error_message=message)
        run_repo.set_status(env.run_id, "failed")
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_failed",
            message=message,
        )
