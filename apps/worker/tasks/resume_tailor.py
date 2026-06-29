"""
Handler for resume_tailor tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a strategically tailored resume for a target job.

Pipeline (6 LLM calls, Steps 2-3 run in parallel):
  1. Load all data (Job, JobReport, FitReport, Profile + StructuredResume)
  2. (parallel) Workstream analysis — role → capabilities → evidence requirements
  3. (parallel) Experience decomposition — bullets → fact atoms → workflows
  4. Evidence matching — requirements ↔ candidate facts
  5. Claim design + section story + edit operations
  6. Write revised bullets
  7. Audit

Input (from run.input_snapshot_json):
  { "job_id": str, "candidate_profile_id": str | None, "preferences": dict | None }

Requires: JobReport + FitReport for the job (generated beforehand).
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError

from packages.contracts.api.runs import ResumeTailorInput
from packages.contracts.reports.resume_tailor import (
    AuditResult,
    BulletEdit,
    EvidenceMatch,
    EvidenceRequirement,
    ExperienceWorkflow,
    FactAtom,
    ResumeTailorDraft,
    SectionPlan,
    WorkstreamAnalysis,
)
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.infrastructure.db.repositories import (
    ArtifactRepository,
    FitReportRepository,
    JobReportRepository,
    JobRepository,
    ProfileRepository,
    RunRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session
from packages.infrastructure.llm.client import LLMCallError, get_llm_client

logger = logging.getLogger(__name__)


def handle_resume_tailor(env: TaskEnvelope) -> dict:
    from packages.infrastructure.llm.usage_writer import set_llm_context
    set_llm_context(run_id=env.run_id, task_id=env.task_id,
                    workspace_id=env.workspace_id, call_site="resume_tailor")

    logger.info("resume_tailor: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    # ------------------------------------------------------------------
    # Step 1: Load all data
    # ------------------------------------------------------------------
    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        snap = run.input_snapshot_json or {}

    try:
        inp = ResumeTailorInput.model_validate(snap)
    except ValidationError as exc:
        return _fail(env, "INVALID_INPUT", f"Invalid resume_tailor input: {exc}")

    with get_session() as session:
        job = JobRepository(session).get(inp.job_id)
        if not job:
            return _fail(env, "JOB_NOT_FOUND", f"Job {inp.job_id} not found")
        jd_text = job.jd_text or ""
        job_title = job.title
        job_company = job.company

        profile_id = inp.candidate_profile_id
        if profile_id:
            profile = ProfileRepository(session).get_by_id(profile_id)
        else:
            profile = ProfileRepository(session).get_for_workspace(env.workspace_id)
        if not profile:
            return _fail(env, "MISSING_PROFILE", "No candidate profile found")
        resolved_profile_id = profile.id
        structured_resume = profile.structured_resume_json
        experience_summary = profile.experience_summary or ""

        if not structured_resume or not structured_resume.get("experiences"):
            return _fail(env, "MISSING_STRUCTURED_RESUME",
                         "Profile has no structured resume. Import your resume first.")

        job_report = JobReportRepository(session).get_latest_active(inp.job_id)
        if not job_report:
            return _fail(env, "MISSING_JOB_REPORT",
                         "No job report found. Generate a job report first.")
        job_report_structured = job_report.structured_json or {}

        fit_structured: dict = {}
        fit_reports = FitReportRepository(session).list_summaries_for_workspace(
            workspace_id=env.workspace_id, profile_id=resolved_profile_id,
        )
        for fr in fit_reports:
            if fr.job_id == inp.job_id:
                full_fr = FitReportRepository(session).get(fr.id)
                if full_fr:
                    fit_structured = full_fr.structured_json or {}
                break

    experiences = structured_resume.get("experiences", [])

    with get_session() as session:
        TaskEventRepository(session).append(
            task_id=env.task_id, run_id=env.run_id,
            event_type="resume_tailor_started",
            message=f"Tailoring resume for {job_title} @ {job_company}",
        )

    llm = get_llm_client()

    # ------------------------------------------------------------------
    # Steps 2 & 3: Parallel — workstream analysis + experience decomposition
    # ------------------------------------------------------------------
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_ws = pool.submit(
            _step_workstream_analysis, llm, jd_text, job_report_structured
        )
        future_facts = pool.submit(
            _step_experience_decomposition, llm, experiences, experience_summary
        )
        workstream_analysis = future_ws.result()
        fact_atoms, experience_workflows = future_facts.result()

    # ------------------------------------------------------------------
    # Step 4: Evidence matching
    # ------------------------------------------------------------------
    evidence_matches = _step_evidence_matching(
        llm, workstream_analysis, fact_atoms, experience_workflows, fit_structured
    )

    # ------------------------------------------------------------------
    # Step 5: Claim design + section story + edit operations
    # ------------------------------------------------------------------
    section_plans, bullet_edits = _step_claim_design(
        llm, workstream_analysis, evidence_matches, experiences, inp.preferences
    )

    # ------------------------------------------------------------------
    # Step 6: Write revised bullets
    # ------------------------------------------------------------------
    revised_markdown = _step_write_bullets(
        llm, section_plans, bullet_edits, experiences, structured_resume
    )

    # ------------------------------------------------------------------
    # Step 7: Audit
    # ------------------------------------------------------------------
    audit = _step_audit(
        llm, structured_resume, revised_markdown, bullet_edits, workstream_analysis
    )

    draft = ResumeTailorDraft(
        workstream_analysis=workstream_analysis,
        fact_atoms=fact_atoms,
        experience_workflows=experience_workflows,
        evidence_matches=evidence_matches,
        section_plans=section_plans,
        bullet_edits=bullet_edits,
        revised_resume_markdown=revised_markdown,
        audit=audit,
    )

    # Write artifacts to disk
    import os
    artifacts_dir = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")
    run_dir = Path(artifacts_dir) / env.run_id / env.task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    resume_path = run_dir / "revised_resume.md"
    resume_path.write_text(revised_markdown, encoding="utf-8")

    draft_path = run_dir / "tailor_draft.json"
    draft_path.write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    with get_session() as session:
        run_repo = RunRepository(session)
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        artifact_repo = ArtifactRepository(session)

        artifact_repo.create(
            run_id=env.run_id, task_id=env.task_id,
            artifact_type="revised_resume",
            storage_uri=str(resume_path),
        )
        artifact_repo.create(
            run_id=env.run_id, task_id=env.task_id,
            artifact_type="tailor_draft",
            storage_uri=str(draft_path),
        )

        run_repo.complete(env.run_id, status="succeeded", result_summary={
            "validation_status": "passed",
            "job_id": inp.job_id,
            "profile_id": resolved_profile_id,
            "bullet_edits_count": len(bullet_edits),
            "audit_passed": audit.passed,
            "audit_issues": len(audit.issues),
            "draft": draft.model_dump(),
        })
        task_repo.mark_succeeded(env.task_id)
        event_repo.append(
            task_id=env.task_id, run_id=env.run_id,
            event_type="task_succeeded",
            message=f"Resume tailored: {len(bullet_edits)} edits, audit {'passed' if audit.passed else 'has issues'}",
        )

    logger.info("resume_tailor: task_id=%s succeeded", env.task_id)
    return {"status": "succeeded", "task_id": env.task_id}


# ---------------------------------------------------------------------------
# LLM step implementations
# ---------------------------------------------------------------------------

_WORKSTREAM_PROMPT = """\
You are analyzing a job posting to understand what the role actually requires.

Given the JD text and a structured job report, produce:
1. workstreams: 3-5 real work activities this person does daily
2. capabilities: the underlying abilities needed for each workstream
3. evidence_requirements: for each capability, what evidence should appear \
in a resume to prove the candidate has it

Focus on operational reality, not JD buzzwords. \
"Strong analytical skills" is not a capability — "can diagnose why an output changed" is.

Return valid JSON matching the schema."""

_DECOMPOSE_PROMPT = """\
You are decomposing a candidate's resume into fact atoms and experience workflows.

For each bullet in each experience:
- Extract fact atoms: context, action, method, output, stakeholder, impact
- Only extract what is stated or strongly implied. Do NOT invent facts.

Then group related fact atoms into experience workflows — chains of work \
that together demonstrate a capability (e.g., "received ambiguous request → \
gathered data → built analysis → presented to stakeholders").

Return valid JSON matching the schema."""

_MATCH_PROMPT = """\
You are matching a candidate's experience evidence against a job's capability requirements.

For each evidence_requirement from the workstream analysis, determine:
- Is there direct evidence (candidate did very similar work)?
- Adjacent evidence (different context but same underlying capability)?
- Supporting evidence (contributes but doesn't prove alone)?
- Gap (job needs this but candidate has no evidence)?

Use the fit report analysis as a reference but do bullet-level matching.

Return valid JSON matching the schema."""

_CLAIM_PROMPT = """\
You are designing the editing strategy for a resume tailored to a specific role.

For each experience section, design:
1. section_plan: what story this section should tell, ordered bullet claims
2. bullet_edits: for each bullet, choose an operation:
   - keep: already proves the right claim
   - light_edit: right fact, needs minor wording adjustment
   - reframe: good fact but wrong angle — rewrite to prove target capability
   - compress: too long, condense while keeping the claim
   - replace: weak bullet, use a stronger fact from the same experience

Each bullet_edit must have:
- claim: what this bullet should prove
- rationale: why this edit operation was chosen
- evidence_strength: direct/adjacent/supporting

Do NOT invent facts. Only use evidence from the candidate's actual experience.
Do NOT turn every bullet into a keyword-stuffed mess — be selective and strategic.

Return valid JSON matching the schema."""

_WRITE_PROMPT = """\
You are writing the final tailored resume bullets based on the editing plan.

Rules:
- Each bullet must fulfill its assigned claim
- Use only facts from the original resume (no fabrication)
- Keep/light_edit bullets should stay very close to the original
- Reframe bullets change the angle but keep the same underlying facts
- Compress bullets shorten without losing the core claim
- Replace bullets use a different (stronger) fact from the SAME experience
- Preserve section-level story arc
- Respect layout: aim for similar line count as the original

Output the complete revised resume in markdown format.

Return valid JSON with the revised_resume_markdown field."""

_AUDIT_PROMPT = """\
You are auditing a tailored resume against the original.

Check for:
1. Fabrication: any claim not grounded in the original resume
2. Keyword stuffing: generic buzzwords added without evidence
3. Identity shift: does the resume still represent the same person?
4. Claim coherence: does each bullet prove a clear, non-redundant claim?
5. Story arc: does each section tell a coherent narrative?
6. Gaps honesty: are real gaps hidden or honestly acknowledged?

Return passed=true only if no critical issues found.
For each issue found, specify severity (critical/warning), the problem, \
and which pipeline step should be revisited to fix it.

Return valid JSON matching the schema."""


def _step_workstream_analysis(llm, jd_text: str, job_report: dict) -> WorkstreamAnalysis:
    user_msg = (
        f"<jd_text>\n{jd_text[:12000]}\n</jd_text>\n\n"
        f"<job_report>\n{json.dumps(job_report, indent=2)[:8000]}\n</job_report>"
    )
    return llm.complete_structured(
        system_prompt=_WORKSTREAM_PROMPT,
        user_prompt=user_msg,
        response_schema=WorkstreamAnalysis,
        max_tokens=4096,
        temperature=0.2,
    )


def _step_experience_decomposition(llm, experiences: list[dict], experience_summary: str) -> tuple[list[FactAtom], list[ExperienceWorkflow]]:
    class _DecompOutput(WorkstreamAnalysis.__class__.__bases__[0]):
        fact_atoms: list[FactAtom] = []
        experience_workflows: list[ExperienceWorkflow] = []

    from pydantic import BaseModel as _BM

    class DecompOutput(_BM):
        fact_atoms: list[FactAtom] = []
        experience_workflows: list[ExperienceWorkflow] = []

    exp_text = json.dumps(experiences, indent=2)[:15000]
    profile_ctx = ""
    if experience_summary:
        profile_ctx = f"\n\n<experience_summary>\n{experience_summary[:3000]}\n</experience_summary>"

    result = llm.complete_structured(
        system_prompt=_DECOMPOSE_PROMPT,
        user_prompt=f"<experiences>\n{exp_text}\n</experiences>{profile_ctx}",
        response_schema=DecompOutput,
        max_tokens=6144,
        temperature=0.2,
    )
    return result.fact_atoms, result.experience_workflows


def _step_evidence_matching(
    llm, workstream: WorkstreamAnalysis, facts: list[FactAtom],
    workflows: list[ExperienceWorkflow], fit_structured: dict,
) -> list[EvidenceMatch]:
    from pydantic import BaseModel as _BM

    class MatchOutput(_BM):
        evidence_matches: list[EvidenceMatch] = []

    user_msg = (
        f"<evidence_requirements>\n{json.dumps([r.model_dump() for r in workstream.evidence_requirements], indent=2)}\n</evidence_requirements>\n\n"
        f"<fact_atoms>\n{json.dumps([f.model_dump() for f in facts], indent=2)[:8000]}\n</fact_atoms>\n\n"
        f"<experience_workflows>\n{json.dumps([w.model_dump() for w in workflows], indent=2)[:4000]}\n</experience_workflows>\n\n"
        f"<fit_report_context>\n{json.dumps(fit_structured, indent=2)[:4000]}\n</fit_report_context>"
    )
    result = llm.complete_structured(
        system_prompt=_MATCH_PROMPT,
        user_prompt=user_msg,
        response_schema=MatchOutput,
        max_tokens=4096,
        temperature=0.2,
    )
    return result.evidence_matches


def _step_claim_design(
    llm, workstream: WorkstreamAnalysis, matches: list[EvidenceMatch],
    experiences: list[dict], preferences: dict | None,
) -> tuple[list[SectionPlan], list[BulletEdit]]:
    from pydantic import BaseModel as _BM

    class ClaimOutput(_BM):
        section_plans: list[SectionPlan] = []
        bullet_edits: list[BulletEdit] = []

    pref_text = ""
    if preferences:
        pref_text = f"\n\n<preferences>\n{json.dumps(preferences, indent=2)}\n</preferences>"

    user_msg = (
        f"<evidence_requirements>\n{json.dumps([r.model_dump() for r in workstream.evidence_requirements], indent=2)}\n</evidence_requirements>\n\n"
        f"<evidence_matches>\n{json.dumps([m.model_dump() for m in matches], indent=2)}\n</evidence_matches>\n\n"
        f"<original_experiences>\n{json.dumps(experiences, indent=2)[:12000]}\n</original_experiences>"
        f"{pref_text}"
    )
    result = llm.complete_structured(
        system_prompt=_CLAIM_PROMPT,
        user_prompt=user_msg,
        response_schema=ClaimOutput,
        max_tokens=6144,
        temperature=0.3,
    )
    return result.section_plans, result.bullet_edits


def _step_write_bullets(
    llm, plans: list[SectionPlan], edits: list[BulletEdit],
    experiences: list[dict], structured_resume: dict,
) -> str:
    from pydantic import BaseModel as _BM

    class WriteOutput(_BM):
        revised_resume_markdown: str = ""

    user_msg = (
        f"<section_plans>\n{json.dumps([p.model_dump() for p in plans], indent=2)}\n</section_plans>\n\n"
        f"<bullet_edits>\n{json.dumps([e.model_dump() for e in edits], indent=2)}\n</bullet_edits>\n\n"
        f"<original_resume_markdown>\n{structured_resume.get('markdown', '')[:10000]}\n</original_resume_markdown>"
    )
    result = llm.complete_structured(
        system_prompt=_WRITE_PROMPT,
        user_prompt=user_msg,
        response_schema=WriteOutput,
        max_tokens=6144,
        temperature=0.3,
    )
    return result.revised_resume_markdown


def _step_audit(
    llm, original_resume: dict, revised_markdown: str,
    edits: list[BulletEdit], workstream: WorkstreamAnalysis,
) -> AuditResult:
    user_msg = (
        f"<original_resume>\n{original_resume.get('markdown', '')[:8000]}\n</original_resume>\n\n"
        f"<revised_resume>\n{revised_markdown[:8000]}\n</revised_resume>\n\n"
        f"<bullet_edits>\n{json.dumps([e.model_dump() for e in edits], indent=2)[:6000]}\n</bullet_edits>\n\n"
        f"<workstream_analysis>\n{json.dumps(workstream.model_dump(), indent=2)[:4000]}\n</workstream_analysis>"
    )
    return llm.complete_structured(
        system_prompt=_AUDIT_PROMPT,
        user_prompt=user_msg,
        response_schema=AuditResult,
        max_tokens=2048,
        temperature=0.2,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fail(env: TaskEnvelope, error_code: str, message: str) -> dict:
    logger.error("resume_tailor: %s — %s", error_code, message)
    with get_session() as session:
        TaskRepository(session).mark_failed(env.task_id, error_code=error_code, error_message=message)
        RunRepository(session).set_status(env.run_id, "failed")
        TaskEventRepository(session).append(
            task_id=env.task_id, run_id=env.run_id,
            event_type="task_failed", message=message,
        )
    return {"status": "failed", "task_id": env.task_id}
