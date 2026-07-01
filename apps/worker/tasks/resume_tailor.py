"""
Handler for resume_tailor tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a strategically tailored resume for a target job.

Pipeline (9 LLM calls, plus up to 1 bounded repair pass):
  1.  Load all data (Job, JobReport, FitReport, Profile + StructuredResume)
  1.5 (parallel) Role capability inference — raw material: capabilities the
      role implies but the JD never states, independently inferred from
      business_context + daily_workflow + full JD text (not from
      underlying_skill_demands, to avoid anchoring on a finished list)
  2.  Workstream analysis (runs after 1.5) — JobReport + inferred capabilities
      → evidence requirements, each tagged provenance=stated|inferred
  3a. (parallel with 1.5) Experience story reconstruction — bullets + role context → rich narratives
  3b. Fact atom extraction — stories → structured fact atoms
  4.  Evidence matching — requirements ↔ fact atoms (informed by stories)
  4.5 Resume strategy — the free-thinking step: overall fit, resume thesis,
      a foreground/bridge/omit decision per capability, section space budget
  5.  Bullet planning — executes resume_strategy: claim + evidence + framing per bullet
  6.  Constrained writing — write bullets from plan + stories
  7.  Audit — if critical issues are found, one repair pass re-runs the
      earliest affected step (bullet_planning or writing) with the audit's
      findings as feedback, then re-audits once. The repair result is
      accepted either way — this is a single bounded pass, not a loop.

Input (from run.input_snapshot_json):
  { "job_id": str, "candidate_profile_id": str | None, "preferences": dict | None }

Requires: JobReport + FitReport for the job (generated beforehand).
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import ValidationError

from packages.contracts.api.runs import ResumeTailorInput
from packages.contracts.reports.resume_tailor import (
    BREADTH_NO_JD_MATCH,
    AuditIssue,
    AuditResult,
    CapabilityStrategy,
    EvidenceMatch,
    EvidenceRequirement,
    ExperienceStory,
    FactAtom,
    RoleCapabilityInference,
    ResumeStrategy,
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

    import os
    from packages.infrastructure.llm.client import LLMClient
    _RESUME_TAILOR_MODEL = os.environ.get("RESUME_TAILOR_MODEL", "gpt-5.4-mini")
    llm = LLMClient(model=_RESUME_TAILOR_MODEL)
    logger.info("resume_tailor: using model=%s", _RESUME_TAILOR_MODEL)

    artifacts_dir = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")
    run_dir = Path(artifacts_dir) / env.run_id / env.task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    def _save_step(step_name: str, data) -> None:
        """Persist step output to disk + TaskEvent immediately."""
        if hasattr(data, "model_dump"):
            payload = data.model_dump()
        elif isinstance(data, list) and data and hasattr(data[0], "model_dump"):
            payload = [d.model_dump() for d in data]
        else:
            payload = data

        step_path = run_dir / f"step_{step_name}.json"
        step_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

        with get_session() as session:
            TaskEventRepository(session).append(
                task_id=env.task_id, run_id=env.run_id,
                event_type=f"step_completed_{step_name}",
                message=f"Step {step_name} completed",
                payload_json={"step": step_name, "artifact_path": str(step_path)},
            )

    # ------------------------------------------------------------------
    # Steps 1.5 & 3a: Parallel — role capability inference + story reconstruction
    # ------------------------------------------------------------------
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_inference = pool.submit(
            _step_role_capability_inference, llm, jd_text, job_report_structured
        )
        future_stories = pool.submit(
            _step_story_reconstruction, llm, experiences, experience_summary
        )
        role_capability_inference = future_inference.result()
        experience_stories = future_stories.result()

    _save_step("role_capability_inference", role_capability_inference)
    _save_step("experience_stories", experience_stories)

    # ------------------------------------------------------------------
    # Step 2: Workstream analysis — depends on Step1.5's output
    # ------------------------------------------------------------------
    workstream_analysis = _step_workstream_analysis(
        llm, jd_text, job_report_structured, role_capability_inference,
    )
    _save_step("workstream_analysis", workstream_analysis)

    # ------------------------------------------------------------------
    # Step 3b: Extract structured fact atoms from stories
    # ------------------------------------------------------------------
    fact_atoms = _step_fact_extraction(llm, experience_stories)
    _save_step("fact_atoms", fact_atoms)

    # ------------------------------------------------------------------
    # Step 4: Evidence matching
    # ------------------------------------------------------------------
    evidence_matches = _step_evidence_matching(
        llm, workstream_analysis, fact_atoms, experience_stories, fit_structured
    )
    _save_step("evidence_matches", evidence_matches)

    # ------------------------------------------------------------------
    # Step 4.5: Resume strategy — free-thinking step, decides what to do
    # with the evidence before anyone writes a bullet
    # ------------------------------------------------------------------
    resume_strategy = _step_resume_strategy(
        llm, workstream_analysis, evidence_matches, experience_stories, fit_structured
    )
    _save_step("resume_strategy", resume_strategy)

    # ------------------------------------------------------------------
    # Step 5: Bullet planning — executes resume_strategy bullet by bullet
    # ------------------------------------------------------------------
    section_plans = _step_bullet_planning(
        llm, workstream_analysis, evidence_matches, fact_atoms,
        experience_stories, experiences, inp.preferences, resume_strategy,
    )
    _save_step("bullet_plans", section_plans)

    # ------------------------------------------------------------------
    # Step 6: Constrained writing — write bullets from plan + stories
    # ------------------------------------------------------------------
    revised_markdown, unresolved_assembly = _step_write_bullets(
        llm, section_plans, experience_stories, structured_resume
    )
    _save_step("revised_markdown", {"markdown": revised_markdown})
    if unresolved_assembly:
        _save_step("assembly_unresolved", {"unresolved": unresolved_assembly})

    # ------------------------------------------------------------------
    # Step 7: Audit (+ one bounded repair pass if it finds critical issues)
    # ------------------------------------------------------------------
    audit = _step_audit(
        llm, structured_resume, revised_markdown, section_plans, workstream_analysis,
        fact_atoms, resume_strategy, unresolved_assembly,
    )
    _save_step("audit", audit)

    repaired = False
    if not audit.passed:
        repair_result = _attempt_repair(
            llm, audit, workstream_analysis, evidence_matches, fact_atoms,
            experience_stories, experiences, inp.preferences, resume_strategy,
            structured_resume, section_plans,
        )
        if repair_result is not None:
            repaired = True
            section_plans, revised_markdown, audit = repair_result
            _save_step("bullet_plans_repaired", section_plans)
            _save_step("revised_markdown_repaired", {"markdown": revised_markdown})
            _save_step("audit_repaired", audit)
            logger.info(
                "resume_tailor: repair pass complete, audit now passed=%s",
                audit.passed,
            )

    draft = ResumeTailorDraft(
        role_capability_inference=role_capability_inference,
        workstream_analysis=workstream_analysis,
        experience_stories=experience_stories,
        fact_atoms=fact_atoms,
        evidence_matches=evidence_matches,
        resume_strategy=resume_strategy,
        section_plans=section_plans,
        revised_resume_markdown=revised_markdown,
        audit=audit,
    )

    # Write final artifacts to disk
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

        bullet_count = sum(len(sp.bullet_plans) for sp in section_plans)
        run_repo.complete(env.run_id, status="succeeded", result_summary={
            "validation_status": "passed",
            "job_id": inp.job_id,
            "profile_id": resolved_profile_id,
            "overall_fit": resume_strategy.overall_fit,
            "bullet_plans_count": bullet_count,
            "repair_attempted": repaired,
            "audit_passed": audit.passed,
            "audit_issues": len(audit.issues),
            "draft": draft.model_dump(),
        })
        task_repo.mark_succeeded(env.task_id)
        event_repo.append(
            task_id=env.task_id, run_id=env.run_id,
            event_type="task_succeeded",
            message=f"Resume tailored: {bullet_count} bullets planned, audit {'passed' if audit.passed else 'has issues'}"
                    f"{' (after repair pass)' if repaired else ''}",
        )

    logger.info("resume_tailor: task_id=%s succeeded", env.task_id)
    return {"status": "succeeded", "task_id": env.task_id}


# ---------------------------------------------------------------------------
# LLM step implementations
# ---------------------------------------------------------------------------

_ROLE_CAPABILITY_INFERENCE_PROMPT = """\
You are inferring capabilities a role implicitly requires, beyond what the \
job posting explicitly states.

## Why this step exists

A job posting never states everything an experienced hiring manager would \
actually expect. Someone evaluating candidates for this type of role at \
this type of company carries assumptions the JD writer didn't bother to \
spell out — because to them, those things go without saying. Your job is \
to surface those unstated assumptions.

This is different from summarizing the JD. You are not extracting phrases — \
you are reasoning from role archetype: "given what this role actually does \
day to day and why it exists, what would someone experienced in this field \
assume a strong candidate brings, even though the posting never said so?"

## What you receive

- business_context: why this role exists, what problem it solves
- daily_workflow: the actual inputs, analyses, outputs, and stakeholders of \
the day-to-day work
- jd_text: the full job posting — read it for texture (company stage, team \
size signals, tone, what's emphasized vs. mentioned in passing), not to \
extract more explicit requirements. Explicit requirements are already \
handled elsewhere; that is not your job here.

You do NOT receive the role's already-extracted explicit skill list. This is \
intentional — your job is to think independently, not to check a list for \
gaps.

## How to infer

For each candidate capability, ask: "If I were screening resumes for this \
role and this type of company, what would I silently expect, that this \
posting never wrote down?" Sources of this kind of inference:

- Industry/role-standard expectations (e.g. a role doing recurring SQL work \
against production data almost always also needs query performance/data \
quality judgment, even if the JD only says "write SQL")
- Company-stage or team-size signals in the JD text (a small team implies \
more end-to-end ownership than a JD's narrow task list suggests)
- What the daily_workflow's inputs/outputs imply about adjacent skills \
needed to actually produce them, even if not named

## This is raw material — generate broadly, don't pre-filter

List every plausible implicit capability you can think of, including ones \
you're not fully sure about. Do not limit yourself to only the most obvious \
or highest-confidence ones — compression and filtering happen in later \
steps, which have more context (including the actual candidate's evidence) \
to judge what's worth keeping. Your job is to not miss anything plausible, \
not to decide what survives. Producing too few because you only wrote down \
your safest guesses is a worse failure than producing a generous list with \
honest confidence ratings.

That said, every entry must have a real reasoning chain (industry pattern, \
company-stage signal, or workflow implication) — do not invent capabilities \
with no connection to the actual business_context/daily_workflow/JD texture \
you were given. Return at most 20 capabilities — if you have more candidates \
than that, keep the ones with the clearest reasoning.

## Confidence and importance_hint are two separate judgments

- confidence: how sure are you this is a genuine implicit expectation for \
this role? "high" = near-universal for this role archetype. "medium" = \
plausible, reasonably well-grounded. "low" = a real possibility but a real \
guess.
- importance_hint: IF this capability is genuinely needed, how central would \
it be? This is independent of confidence — you can be very sure (high \
confidence) that something is only a nice-to-have, or unsure (low \
confidence) about something that would be core if true.

Return valid JSON matching the schema."""

_WORKSTREAM_PROMPT = """\
You are transforming a pre-analyzed Job Intelligence Report into evidence \
requirements for resume tailoring.

## What you receive

A structured Job Intelligence Report that has already deeply analyzed this role:
- business_context: why the role exists and what problem it solves
- position_function: primary/secondary functions and their mix
- daily_workflow: inputs, analyses, outputs, and stakeholders
- underlying_skill_demands: each entry has a jd_phrase (the literal JD \
wording — supporting evidence only, never a capability label itself) and an \
underlying_capability (the synthesized, canonical capability name). \
**Always use underlying_capability as the capability text. Never use \
jd_phrase as if it were a separate capability** — treating both fields from \
the same entry as two different capabilities is the most common way \
duplicate evidence_requirements slip past deduplication, because the two \
strings don't look alike even though they're the same requirement.

Also:
- inferred_capabilities: additional candidate capabilities NOT explicitly \
stated in the JD, independently inferred by a separate analysis step from \
business_context, daily_workflow, and the full JD text. Each one is tagged \
with confidence (how sure the inference is) and importance_hint (how central \
it would be if real). These are raw material, not settled conclusions — you \
decide which ones earn a place as an evidence_requirement. See the dedicated \
section below for how to handle them.

The Job Report is your PRIMARY SOURCE. Do not re-analyze the JD from scratch. \
The JD text is provided only as reference for resolving ambiguity.

## Step 1: Synthesize workstreams

Compress the daily_workflow and position_function into 3-5 workstreams.

A workstream is a recurring work loop with four parts:
- Trigger: what causes the work (a request arrives, a cycle begins, an issue surfaces)
- Process: what the person does with judgment (not mechanical execution)
- Output: what gets produced, decided, or changed
- Consumer: who uses the output or is affected

How to derive workstreams:
1. Read daily_workflow.likely_inputs and likely_analyses — these are the raw activities
2. Group related activities that serve the same business purpose
3. Name each group as a concrete work loop, not an abstract skill

Good workstream: "Investigate model behavior through PnL decomposition and \
sensitivity analysis, identify methodology issues, and report findings to \
governance committees for remediation decisions"

Not a workstream:
- "Strong analytical skills" (abstract trait, not a work loop)
- "Run SQL queries" (a method inside a workstream, not a workstream itself)
- "Data analysis" (too vague — what data? what question? for whom?)

For each workstream, attach the capabilities from underlying_skill_demands \
that it primarily requires, plus any inferred_capabilities you've decided to \
promote (see "Handling inferred_capabilities" below) that fit this \
workstream. Carry forward the demand_type and importance \
from the Job Report. A capability may serve multiple workstreams.

## Step 2: Derive evidence requirements

This is the core reasoning step. For each DISTINCT capability, derive what \
evidence must appear in a resume to prove the candidate has it.

### Canonicalize capabilities first (mandatory)

A capability that serves multiple workstreams must produce exactly ONE \
evidence_requirement, not one per workstream. Before writing any \
evidence_requirement:

1. List every capability that appears across all workstreams.
2. Merge capabilities that are the same underlying ability worded slightly \
differently (e.g. "write complex SQL" appearing under three workstreams is \
ONE capability, not three).
3. For each merged capability, pick the single workstream it is most \
central to for the `workstream` field. If it genuinely serves several \
workstreams equally, say so in the `reasoning` field instead of repeating \
the evidence_requirement.

Downstream steps match each evidence_requirement against the candidate's \
evidence exactly once. If the same capability appears as multiple \
evidence_requirement entries, downstream matching will judge it \
independently each time and can produce contradictory verdicts (e.g. \
"supporting" for one copy, "gap" for another) for what is really one \
question. Producing duplicates is a correctness bug, not thoroughness.

### Handling inferred_capabilities (mandatory)

underlying_skill_demands are grounded in explicit JD phrases — treat them as \
established without re-litigating whether the role actually needs them.

inferred_capabilities are different: they are hypotheses from a separate \
analysis step, not settled facts. For each one, decide whether it earns a \
place as a full evidence_requirement:

- Cross-check it against business_context and daily_workflow — does the \
actual texture of this role support it, or is it a generic guess that could \
apply to any role in this field?
- A "high" confidence inference with clear daily_workflow support can be \
promoted with importance up to its importance_hint.
- A "low" confidence inference should only be promoted if you find \
independent support in business_context/daily_workflow, and even then it \
should rarely exceed "supporting" importance — do not promote a low-confidence \
guess to "core" just because importance_hint said core. importance_hint is \
the inference step's best guess, not a directive.
- If an inferred capability has no support beyond the original guess, leave \
it out entirely. inferred_capabilities are candidates to evaluate, not an \
obligation to include — a long list of weak guesses padding out the \
evidence_requirements is worse than leaving them out.

Every evidence_requirement you produce must set `provenance`: "stated" if it \
came from underlying_skill_demands, "inferred" if it came from \
inferred_capabilities (even after you've corroborated it with \
business_context/daily_workflow — the provenance reflects where the \
capability was first identified, not how confident you ended up being in it).

### Reasoning method

For each capability, ask: "If someone truly has this capability, what would \
their work history look like?"

Think through four layers:

1. **Situation signal** — What kind of problem or context would they have faced?
   - What triggers this type of work?
   - What makes it non-trivial? (ambiguity, scale, conflicting inputs, stakes)

2. **Action pattern** — What specific actions would they have taken?
   - Not generic verbs ("managed", "led", "supported")
   - Specific work actions: designed a framework, reconciled conflicting data, \
built an automation, translated findings for a non-technical audience
   - What judgment calls would they have made?

3. **Output / impact signal** — What would they have produced or changed?
   - A deliverable (report, model, dashboard, process document)?
   - A decision enabled (stakeholder acted on their analysis)?
   - A system improved (reduced errors, faster cycle, broader coverage)?

4. **Ownership distinguisher** — What separates someone who HAS this capability \
from someone who merely worked near it?
   - "Supported data analysis" ≠ "designed the analytical framework"
   - "Participated in model review" ≠ "identified the methodology flaw that \
changed the risk rating"
   - Look for: problem scoping, method selection, independent judgment, \
adoption by others

### Worked example

Capability: "can turn an ambiguous operational problem into a repeatable \
analytical workflow"
Workstream: "Build and maintain analytical processes for recurring business questions"
Importance: core

Evidence checklist:
- Encountered a problem that was ill-defined or had no existing process
- Gathered and reconciled information from multiple or messy sources
- Designed an analytical approach (not just executed an existing one)
- Built something repeatable (template, automation, documented methodology)
- Output was adopted by stakeholders (not a one-off personal exercise)
- Demonstrated scoping judgment — chose what to include and what to exclude

Reasoning: This capability requires evidence of the full ambiguity-to-structure \
cycle. Someone who only "ran reports" or "performed analysis as requested" has \
not proven they can handle the ambiguity-to-structure transition. The key \
distinguisher is evidence of DESIGNING the approach, not just executing it. \
Look for: problem definition, method design, and adoption/reuse by others.

### Calibration rules

- For "core" capabilities: 4-6 checklist items covering the full work cycle \
(situation → action → output → impact)
- For "supporting" capabilities: 2-3 items focused on the key differentiator
- For "nice_to_have" capabilities: 1-2 items
- Each checklist item must be concrete enough to match against a resume bullet \
— if it could apply to any job, it is too vague
- Order checklist items to follow the natural work sequence
- The reasoning field must explain what distinguishes real evidence from \
surface-level keyword matches
- No two evidence_requirements may have the same (or near-duplicate) \
capability text. Before returning, scan your own evidence_requirements list \
and merge any duplicates you find — this includes checking whether you \
accidentally used both a jd_phrase and its underlying_capability as if they \
were two separate capabilities.
- Every evidence_requirement must set provenance to "stated" or "inferred" \
— never leave it at its default.

Return valid JSON matching the schema."""

_STORY_PROMPT = """\
You are reconstructing the full experience story behind a candidate's \
resume bullets.

## Why this step matters

Resume bullets are extremely compressed — they capture maybe 10-20% of \
what someone actually did. A bullet like "Evaluated predictive models" \
hides an entire work process: understanding model assumptions, gathering \
data, choosing evaluation criteria, running tests, interpreting results, \
drafting findings, presenting to stakeholders.

Your job is to decompress each experience section into a rich picture of \
what this person ACTUALLY did — not just what they wrote down. This \
reconstructed story becomes the raw material for resume tailoring, so \
downstream steps work from a complete understanding rather than rephrasing \
compressed bullets.

## How to reconstruct the story

### Step 1: Establish role context

Before reading the bullets, think about what this TYPE of role at this \
TYPE of company typically involves:
- What does a [title] at [employer type] usually do?
- What's their typical scope of responsibility given tenure length?
- What team do they likely sit in? Who do they report to?
- What are the standard work loops in this function?

This gives you a PRIOR — a baseline expectation of what this person did.

### Step 2: Read all bullets as a collection

Do NOT read bullets one by one. Read them all at once and ask:
- What overall picture do these bullets paint together?
- Do some bullets form a sequence? (identified problem → built solution → \
delivered impact)
- What capabilities emerge from the COMBINATION that no single bullet proves?

Example: if someone lists "evaluated models" AND "built challenger models", \
they didn't just validate — they owned the full model lifecycle. Neither \
bullet alone proves this, but together they do.

### Step 3: Fill in the gaps

Based on role context + bullet combination, infer work that almost certainly \
happened but wasn't written:
- What inputs did they work with? (data sources, systems, documents)
- What routine tasks are standard for this role?
- What stakeholder interactions were required?
- What judgment calls did they make?

### Step 4: Assess reconstruction quality

Be honest about how much you're inferring:
- Rich bullets (specific actions, methods, outcomes) → high confidence story
- Moderate bullets (some specifics, some gaps) → medium confidence, some inference
- Thin bullets ("Supported analysis", "Assisted with reports") → low confidence, \
heavy inference — say so explicitly rather than inventing specifics

## Output per experience

1. **role_context**: What this type of role at this type of company typically \
involves (1-2 sentences)
2. **narrative**: The full reconstructed story (2-4 paragraphs) — read like a \
knowledgeable colleague describing what this person did
3. **claims**: Structured list of specific claims, each with:
   - claim: what this person did or demonstrated
   - source_bullets: which bullet indices support this ([] if pure inference)
   - confidence: stated / strongly_implied / inferred
   - basis: why you believe this (bullet text, role context, or combination)
4. **reconstruction_confidence**: overall quality assessment
   - high: bullets are rich and specific, story is mostly grounded
   - medium: bullets have gaps, reasonable inference fills them
   - low: bullets are vague/generic, story relies heavily on role-context inference
5. **gaps**: things you cannot determine even with inference

## Rules

- Every claim must be supported by bullet text OR justified by role context.
- Claims with empty source_bullets (pure inference) MUST have confidence \
"inferred" and a clear basis.
- Do not make the person sound more senior or capable than evidence supports.
- When bullets are thin, set reconstruction_confidence to "low" rather than \
inventing specifics.
- gaps should list what a resume reviewer would want to know but cannot determine.

Return valid JSON matching the schema."""

_FACT_EXTRACTION_PROMPT = """\
You are extracting structured fact atoms from reconstructed experience stories.

## What you receive

Experience stories that have already reconstructed the full picture of what \
the candidate did in each role. Each story contains:
- narrative: rich description of the work
- claims: structured claims with confidence levels
- reconstruction_confidence: how much of the story is grounded vs inferred

## What a fact atom is

A fact atom is a single, structured unit of evidence. Each one captures \
one piece of work the candidate did, broken into these fields:

- **context**: The business situation or project context
- **input**: What they worked with (data, problem, request, complexity)
- **action**: What they specifically did
- **method**: How they did it (specific technique, not just a tool name)
- **output**: What they produced
- **stakeholder**: Who consumed the output
- **impact**: Why it mattered
- **boundary**: What this fact does NOT prove (prevents downstream fabrication)
- **confidence**: stated / strongly_implied / inferred — carry forward from \
the story claim that this fact is based on

## Coverage requirement (mandatory)

The input contains one or more experience stories, each tagged with its own \
experience_index. Your fact_atoms output MUST include at least one atom for \
EVERY experience_index present in the input. Do not skip an entire story \
just because another story is richer or appears first — a thinner story \
still needs its own fact atoms, even if that means producing only 1-2 atoms \
marked "inferred" instead of 3-8.

Before returning your answer, check: list every experience_index from the \
input, and confirm each one appears in at least one fact atom's \
experience_index field. If any are missing, go back and extract atoms for \
them before finalizing.

## How to extract

1. Work through EACH story's claims list IN TURN, one story at a time — \
finish extracting atoms for one experience_index before moving to the next, \
so no story gets skipped
2. For each claim (or group of related claims), produce one fact atom
3. A single claim may produce one fact atom. Two closely related claims \
may combine into one richer fact atom.
4. Carry forward source_bullets from the claim to the fact atom's source_bullets
5. Carry forward confidence — do not upgrade: an "inferred" claim produces \
an "inferred" fact atom

## Boundary field

The boundary field is critical. It tells downstream steps what NOT to claim.

Derive it from two sources:
- The story's gaps (things that couldn't be determined)
- The logical limits of what the claim proves

Example: a claim about "evaluated model performance" → boundary: \
"Does NOT prove candidate built or developed models. Proves evaluation \
capability only."

But if the SAME story also has a claim about "built challenger models", \
then the evaluation fact atom's boundary should note: "Model building \
capability is proven by a separate claim — this fact specifically proves \
the evaluation/validation skill."

## Rules

- Produce fact atoms from the story, not by re-reading the original bullets
- One experience story may produce 3-8 fact atoms depending on richness
- If reconstruction_confidence is "low", produce fewer fact atoms and mark \
most as "inferred"
- Every fact atom must trace back to at least one story claim
- Every experience_index present in the input must appear in the output — \
this is a hard requirement, not a suggestion

Return valid JSON matching the schema."""

_MATCH_PROMPT = """\
You are matching a candidate's fact-level experience evidence against a \
job's capability requirements.

## What you receive

- evidence_requirements: what the resume must prove (from workstream analysis), \
each with an evidence_checklist and importance level
- fact_atoms: structured facts extracted from reconstructed experience stories, \
each with context, input, action, method, output, stakeholder, impact, \
boundary, and confidence
- experience_stories: the rich reconstructed narratives of what the candidate \
actually did in each role — use these to understand cross-bullet capabilities \
that individual fact atoms may not fully capture
- fit_report_context: a profile-level fit analysis (strong_matches, \
partial_matches, gaps) — use as directional reference, NOT as ground truth, \
because it was done at profile/skill level, not bullet level

## Your task

For each evidence_requirement, find the best evidence from the candidate's \
experience. Think at TWO levels:

1. **Fact atom level**: which individual fact atoms match the evidence checklist?
2. **Story level**: does the experience story as a whole demonstrate a capability \
that no single fact atom captures? (e.g., "evaluated models" + "built challenger \
models" together prove full model lifecycle ownership)

When multiple fact atoms from the same experience combine to prove a capability, \
list ALL of them in sources. The combined evidence may be stronger than any \
single atom.

## How to cite sources

Each entry in sources has fact_atom_index, experience_index, and contribution.

- If the evidence is fact-atom-level, set fact_atom_index to that atom's index.
- If the evidence is story-level only — the experience_story's narrative \
demonstrates the capability but no individual fact_atom captures it (or \
this experience has no fact_atoms at all) — set fact_atom_index to null \
and use contribution to explain what in the narrative supports the match.
- NEVER set fact_atom_index to an atom that belongs to a different \
experience_index than the one you are citing. If you want to cite evidence \
from experience_index 1 but the only fact_atoms available are from \
experience_index 0, that is not valid fact-atom evidence — either use \
story-level citation (fact_atom_index: null) or mark the capability "gap" \
for that experience.

## How to judge evidence strength

### direct
The candidate did very similar work in a similar context.
- The fact atom's action and output closely match the evidence_checklist items
- The context is the same domain or a closely related one
- The candidate clearly owned the work (not just participated)
- confidence is "stated" or "strongly_implied"

### adjacent
Different context, but the underlying capability is the same.
- The core skill transfers even though the industry, domain, or product differs
- Example: process automation in finance vs process automation in healthcare — \
different domain, same capability
- The candidate must have demonstrated the SAME type of judgment and method, \
not just used a similar tool

### supporting
Contributes to proving the capability but cannot stand alone.
- Partial overlap: the fact atom covers some checklist items but not the full \
work cycle
- Or the candidate assisted/contributed rather than owned the work
- Or the fact atom's confidence is "inferred"
- Supporting evidence can strengthen an adjacent match but never upgrade a gap

### weak
Some signal exists but it is too thin to use in a resume bullet.
- The fact atom is tangentially related at best
- confidence is "inferred" AND boundary excludes the core claim
- Or the match is based on tool/keyword overlap rather than capability overlap
- Weak matches should be documented but will not be used in claim design

### gap
The job needs this capability but the candidate has no meaningful evidence.
- No fact atoms match even partially
- Do not hide gaps — they are important for honest resume positioning
- A gap on a "nice_to_have" is different from a gap on a "core" capability

## Matching rules

- Match against the evidence_checklist, not the capability name. \
"Process improvement" could mean very different things — the checklist \
specifies what evidence actually looks like.
- Check the fact atom's boundary field. If boundary says "does NOT prove X", \
that fact atom cannot be used to match capability X.
- Weight confidence: a "stated" fact atom is stronger evidence than a \
"strongly_implied" one. An "inferred" fact atom can be at most "supporting".
- One capability can be matched by multiple fact atoms (list them all in sources). \
A single fact atom may also contribute to multiple capabilities.
- Carry forward workstream and importance from the evidence_requirement — \
these are needed by downstream claim design.
- The reasoning field should explain WHY this strength level was chosen, \
not just restate the conclusion.
- Every source's fact_atom_index (when set) MUST belong to the same \
experience_index as that source entry. A mismatched index is a fabricated \
citation, not evidence — use fact_atom_index: null with a contribution \
explanation instead.

## How to use the fit report

The fit_report_context provides profile-level matching (strong_matches, \
partial_matches, gaps). Use it as a starting hypothesis:
- If fit report says "strong match" on a capability, look for the specific \
fact atoms that support it — you may confirm or downgrade based on bullet-level evidence
- If fit report says "gap", check carefully — the profile-level analysis may \
have missed bullet-level evidence that the decomposition step surfaced
- Do not copy fit report conclusions. Re-evaluate at fact atom level.

Return valid JSON matching the schema."""

_RESUME_STRATEGY_PROMPT = """\
You are the strategist deciding what argument this resume should make for \
this candidate, for this role — before anyone writes a single bullet.

## Why this step exists

Evidence matching already told you, capability by capability, how strong \
the candidate's evidence is. That is an analytical answer, not a plan. \
Someone still has to decide, looking at ALL of it together: is this \
candidate a good fit for this role at all? What's the one thing the resume \
should make the reader believe? And for each capability, what do we \
honestly DO with the evidence we have — lead with it, translate it, \
mention it in passing, or leave it as an honest gap?

If you skip this and let each bullet get decided independently later, the \
writing step will default to describing whatever the candidate is already \
strongest at, in their native domain — which reads fine on its own but \
quietly stops being an argument for THIS role. Your job is to make that \
argument once, explicitly, so every bullet downstream has something real \
to execute.

## What you receive

- evidence_requirements: the canonical, deduplicated list of capabilities \
this role needs, each with importance and an evidence_checklist
- evidence_matches: how strong the candidate's evidence is for each \
capability (direct / adjacent / supporting / weak / gap), with sources
- experience_stories: the full reconstructed narratives — read these for \
texture and judgment, not just the matches. A story's "gaps" field may \
hint at relevant work that never made it into a fact atom or a bullet.
- fit_report_context: a profile-level fit analysis, directional reference only

## Step 1: Decide overall_fit

Look at the evidence_matches in aggregate, weighted by importance:
- strong_fit: most core capabilities are direct or adjacent
- viable_fit: a mix — real strengths exist, but several core capabilities \
are gaps that an honest resume will have to leave visible
- stretch_fit: core capabilities are mostly adjacent/supporting at best, \
the resume will lean heavily on bridging and transferable framing
- weak_fit: most core capabilities are gaps; there isn't enough real \
evidence to build a credible argument for this specific role

Do not soften this judgment to be encouraging. An honest weak_fit call is \
more useful than a flattering one — it tells the candidate where they \
actually stand.

## Step 2: Write resume_thesis

One to three sentences: "After reading this resume, the hiring manager \
should believe ___." This is the single idea every downstream bullet \
exists to support. It must be grounded in real, strong evidence — not \
aspirational.

## Step 3: Plan the section space budget — decide this BEFORE committing to capabilities

For each experience, decide how many bullets it should carry and what role \
it plays in the overall argument (e.g. "identity + core capability", \
"execution depth", "breadth / secondary evidence only") — based on how much \
real evidence that experience has, not on how many bullets the original \
resume happened to have.

Add up the bullet_count_target across all experiences. **This total is a \
hard ceiling on how many capabilities you can decide to foreground or \
bridge in Step 4.** Decide this number now, before you've looked at \
individual capabilities one by one — that's the only way it reflects a \
real constraint instead of being back-filled to justify whatever you \
already decided to include.

## Step 4: Decide a strategy per capability — within the budget you just set

For EVERY evidence_requirement, make one decision:

- **foreground**: direct (or strong adjacent) evidence exists for a \
core/supporting capability — this should anchor at least one bullet.
- **bridge**: evidence is adjacent — the underlying capability transfers, \
but the bullet must explicitly translate the domain difference. Say in \
reasoning what the bridge actually is, not just "adjacent evidence exists."
- **minimal_mention**: evidence is supporting/weak or the capability is \
nice_to_have — worth a passing reference, not a dedicated bullet.
- **omit_honest_gap**: no real evidence (strength is "gap" or "weak" with \
no plausible bridge) — say so. Do not imply the capability through \
adjacent wording. A resume that hides every gap is not more persuasive, \
it's less trustworthy once a reader probes it.
- **ask_candidate**: a story's narrative or gaps field suggests the \
candidate plausibly has relevant experience that simply never made it into \
fact atoms — note what to ask them, rather than fabricating it now or \
silently treating it as a gap. This only applies when there's a genuine \
textual hint, not as a way to avoid saying "gap."

**foreground and bridge each claim one of the bullet slots from Step 3's \
budget — minimal_mention, omit_honest_gap, and ask_candidate do not.** As \
you go through the list, keep a running count of how many capabilities \
you've marked foreground or bridge. If you reach the budget before you've \
gone through every capability, every remaining one must be minimal_mention, \
omit_honest_gap, or ask_candidate — you do not get to exceed the budget \
because more capabilities deserve a bullet than you have room for. When \
forced to choose which capabilities get the limited slots, prioritize in \
this order: (1) core importance over supporting/nice_to_have, (2) stronger \
evidence (direct over adjacent) over weaker, (3) provenance="stated" over \
provenance="inferred". Before finalizing your output, count your \
foreground+bridge entries again and confirm the total does not exceed the \
Step 3 budget — if it does, downgrade the weakest entries by this same \
priority order until it fits.

### Factor in provenance

Each evidence_requirement carries a provenance field: "stated" means the JD \
explicitly asked for this capability. "inferred" means a separate analysis \
step guessed the role probably needs it even though the JD never said so — \
it is a hypothesis that made it through one round of cross-checking, not a \
confirmed requirement.

For provenance="inferred" capabilities, be more conservative than the \
evidence_matches strength alone would suggest: prefer "bridge" or \
"minimal_mention" over "foreground", even when the candidate's evidence \
looks strong, unless you have good reason to trust the inference (the \
reasoning field should make that case explicit, not just restate the \
evidence). The cost of under-using a real-but-unconfirmed requirement is \
small — the resume just doesn't lead with something that might not matter. \
The cost of foregrounding it on a guess is building part of the resume's \
core argument on a requirement that may not actually exist. When the \
budget forces cuts, an inferred capability should be one of the first \
things downgraded, not one of the last.

## Step 5: List forbidden_claims

Anything the resume must NOT claim, stated plainly — pulled from fact \
atoms' boundary fields and from capabilities you marked omit_honest_gap. \
This is the resume-level version of a bullet's boundary field.

## Rules

- Every evidence_requirement must get exactly one capability_strategies entry.
- The number of capability_strategies entries marked foreground or bridge \
must not exceed the total bullet_count_target across section_space_budget. \
This is checked after you respond — if it's violated, you'll be asked to \
redo it, so get it right the first time rather than relying on a second pass.
- Do not re-litigate evidence_matches' strength judgments — take them as \
given. Your job is deciding what to DO with them, not re-grading them.
- foreground/bridge decisions must be traceable to real strength ratings \
(direct/adjacent) — do not foreground something evidence_matches rated gap.
- Be specific in reasoning. "This is a good fit" is not reasoning. "The \
candidate's challenger-model and backtesting work demonstrates the same \
hypothesis-test-compare rigor the role's experimentation workstream needs, \
even though the domain differs" is reasoning.

## If you are revising a previous attempt

If the user message includes a <previous_attempt_feedback> block, your \
prior attempt marked more capabilities foreground/bridge than your own \
section_space_budget allows. Re-prioritize using the same order as above \
(core > supporting/nice_to_have, direct > adjacent, stated > inferred) — \
downgrade the weakest excess entries to minimal_mention or omit_honest_gap. \
You may also widen the budget slightly if, on reflection, an experience \
genuinely supports one more bullet than you first planned — but the count \
must reconcile this time.

Return valid JSON matching the schema."""

_BULLET_PLANNING_PROMPT = """\
You are designing the complete plan for each resume bullet — what it should \
prove, what evidence to use, and how to frame it for the target role.

## What you receive

- resume_strategy: the plan you must execute — resume_thesis (what the \
reader should believe), capability_strategies (what to do with each \
capability: foreground / bridge / minimal_mention / omit_honest_gap / \
ask_candidate), section_space_budget (how many bullets each experience \
gets and what role it plays), and forbidden_claims
- evidence_requirements: what the role needs proven, with importance levels \
and evidence_checklist
- evidence_matches: which capabilities have evidence, at what strength, \
with specific fact_atom sources
- fact_atoms: structured facts extracted from experience stories (indexed)
- experience_stories: the rich reconstructed narratives of what the candidate \
actually did — use for context and for finding replacement material
- original_experiences: the original resume structure (employer, title, bullets)

## Your task: execute resume_strategy, don't re-decide it

resume_strategy already decided, for the whole resume, which capabilities to \
foreground, which to bridge, which to leave as honest gaps, and how much \
space each experience gets. Your job here is narrower and more concrete: \
turn those decisions into a section_plan for each experience.

Do NOT re-litigate resume_strategy's decisions. If it marked a capability \
"omit_honest_gap", no bullet in your plan may serve that capability, no \
matter how the original bullet text reads. If it marked one "foreground", \
some bullet must actually be built to prove it — don't quietly substitute \
an easier, unrelated claim because it's more natural to write.

For each experience section, produce:
1. A story_arc — how resume_thesis plays out specifically in this section
2. A bullet_plan for each bullet position, following section_space_budget's \
bullet_count_target for that experience (a guideline, not absolute — deviate \
only if the evidence genuinely doesn't support hitting the target, and say \
so in story_arc)

## How to design a section story arc

A section is not a list of random accomplishments. It is an evidence portfolio \
that builds a specific impression, and that impression must serve \
resume_thesis specifically — not just be generically impressive.

Use section_space_budget's role_in_argument for this experience as your \
starting point, then sequence bullets to follow this progression where it \
applies:
1. **Identity**: First bullet establishes WHO this person is in this role — \
their primary function and scope
2. **Core capability**: Next 1-2 bullets prove the foregrounded/bridged \
capabilities resume_strategy assigned to this experience
3. **Execution/method**: Prove HOW they work — process, method, rigor
4. **Impact/stakeholder**: Prove their work MATTERED — who used it, what \
decisions it enabled
5. **Breadth** (if space): Secondary capabilities or governance evidence

Check your arc:
- Does the first bullet build the right identity for the target role?
- Are the capabilities resume_strategy foregrounded actually proven here?
- Does each bullet prove something DIFFERENT?
- Would the reader form the impression resume_thesis describes?

## How to plan each bullet

For each bullet position, make FIVE decisions:

### 1. Claim and serves_capability: what should this bullet prove, for which JD requirement?

Look at resume_strategy.capability_strategies, not evidence_matches \
directly, to decide what this bullet should serve:
- Which capability_strategies entries are "foreground" or "bridge" and \
don't yet have a bullet covering them? Prioritize those, "foreground" first.
- Never assign a claim to a capability resume_strategy marked \
"omit_honest_gap" or "ask_candidate" — those must stay uncovered by design, \
not by oversight.
- Do NOT duplicate claims across bullets — once a capability has a bullet, \
move to the next undone one.

A claim is NOT a sentence. It is a capability statement:
  Good: "Can design automated analytical workflows that replace manual \
processes and are adopted by multiple teams"
  Bad: "Automated reporting workflow"

**serves_capability is mandatory and must be exact.** Set it to the literal \
capability string copied character-for-character from \
resume_strategy.capability_strategies (which matches evidence_requirements \
exactly) — not a paraphrase, not the claim text. This is what lets \
downstream steps verify the bullet actually executes the strategy instead \
of silently describing whatever the candidate happens to be strongest at.

If, after covering every foreground/bridge capability assigned to this \
experience, you still have bullet positions left (per \
section_space_budget), you may use them for identity or breadth — but you \
MUST set serves_capability to the literal string "breadth_no_jd_match" \
rather than inventing a claim about the candidate's native domain and \
leaving serves_capability blank or pointed at something unrelated.

**Do not silently overrule Step4 or resume_strategy.** If \
resume_strategy marked this capability "bridge" (meaning evidence_matches \
rated it "adjacent"), your evidence_strength must also be "adjacent" (not \
upgraded to "direct"), and framing_guidance must explain the bridge — using \
resume_strategy's reasoning for that capability as your starting point. \
Re-labeling adjacent evidence as direct and dropping the bridging language \
defeats the purpose of both Step4's matching and the strategy step's plan.

### 2. Evidence sources: what facts support this claim?

Find the fact atoms that best prove this claim. Reference them by index.
- Prefer fact atoms with confidence "stated" or "strongly_implied"
- An "inferred" fact atom can support but should not be the primary evidence
- Multiple fact atoms can combine to prove one claim
- Only cite a fact_atom whose own experience_index matches the experience \
you are planning this bullet for. Never reference a fact_atom that belongs \
to a different experience, even if its index "looks right" or its content \
seems loosely relevant — that is a fabricated citation, not evidence.
- If fact_atoms contains NO entries for this experience_index at all, do \
NOT invent indices. Leave evidence_source_indices empty, set \
evidence_strength to "supporting" (never "direct" or "adjacent"), and base \
the claim and framing_guidance directly on original_experiences text for \
this bullet instead. State in boundary: "No fact-atom-level evidence \
available for this experience — claim is derived directly from the \
original bullet text only."

### 3. Framing guidance: the concrete writing instruction

This is the most important field. It tells the writing step EXACTLY what \
to do with this bullet. It must be specific enough that a writer can execute \
it without any other context about the target role.

Compare the original bullet against the claim and ask:

**Does the original bullet already prove the claim with the right angle?**
If yes, say so: "Original bullet already proves the claim with correct \
framing. Use as-is with only minor grammar/tense fixes if needed."

**Does the original have the right facts but the wrong angle?**
This is the most common case when someone is transitioning roles. Write \
specific instructions:
- KEEP: which facts/details from the original to preserve
- REMOVE: which details to drop (project names, internal jargon, aspects \
that signal the wrong role type)
- FOREGROUND: what aspect to emphasize instead
- VOCABULARY: what verbs/nouns to use that align with the target role
- ANGLE: what perspective shift is needed

**Is the original bullet about something the target role doesn't need?**
Then the bullet position should be filled with different material from \
the experience story. Write:
- What material to use from the story (cite specific claims or facts)
- What angle to take
- Explicitly note: "Do NOT use the original bullet as reference"

### Worked examples

Example 1 — original is already aligned:
  original: "Built automated Python pipeline for credit data processing"
  claim: "Can build automated data processing pipelines in Python"
  framing_guidance: "Original bullet already proves the claim with the \
right framing. Use as-is. Only fix: add the scale or stakeholder impact \
if space allows."

Example 2 — same facts, wrong angle (most common):
  original: "Led CS-UBS expense model integration: built Python and Copilot \
enabled workflows for data processing, QA checks, and statistical analysis"
  claim: "Can build automated analytical workflows that replace manual processes"
  framing_guidance: "KEEP: built Python workflows, data processing, QA checks, \
statistical analysis, automated recurring tasks. REMOVE: 'Led CS-UBS expense \
model integration' (project-specific context that signals model risk, not \
analytics), Copilot mentions (secondary). FOREGROUND: automation design, \
workflow construction, multi-source data processing. VOCABULARY: 'Built \
automated', 'designed workflow', 'standardized' instead of 'Led integration'. \
The bullet should read as someone who builds analytical tools, not someone \
who managed a model migration."

Example 3 — replace with different material:
  original: "Built Python/R challenger and automated backtesting..."
  claim: "Can translate quantitative findings into governance-ready communication"
  framing_guidance: "The original bullet proves model validation capability, \
which is already covered by bullet 3. This position should prove stakeholder \
communication. Write a NEW bullet using story material: delivered model risk \
reports to governance, translated issues into documented limitations and \
monitoring thresholds, coordinated remediation with developers/business/IT/finance. \
ANGLE: emphasize translating quantitative findings into clear governance outputs. \
Do NOT reference the original bullet content."

### 4. Layout budget

Note the original bullet's approximate length. The revised bullet should \
stay within a similar range. If a claim needs more space, another bullet \
in the section must be compressed.

## Handling gaps

If a capability has evidence_match strength "gap":
- Do NOT design a bullet for it
- Do NOT try to imply the candidate has this capability
- Gaps should remain visible — this is honest positioning

## Rules

- Every claim must be backed by at least one fact_atom from the SAME \
experience_index, unless no such fact_atom exists at all — see the \
no-evidence case in "Evidence sources" above
- serves_capability must exactly match an evidence_requirements[].capability \
string, or be the literal sentinel "breadth_no_jd_match" — never blank, \
never a paraphrase
- Never serve a capability resume_strategy marked "omit_honest_gap" or \
"ask_candidate" — those decisions are final at this step
- evidence_strength must never exceed what evidence_matches already \
determined for serves_capability — you are applying Step4's verdict, not \
re-deciding it
- If evidence_strength is "adjacent", framing_guidance MUST explain how to \
bridge the domain difference
- boundary field: what the bullet must NOT claim, derived from fact atoms' boundaries
- forbidden_claims from resume_strategy apply to every bullet in every section
- Prefer fewer, stronger claims over many weak ones

## If you are revising a previous attempt

If the user message includes a <previous_attempt_feedback> block, an editor \
already reviewed an earlier version of this plan and found real problems — \
listed there with the editor's suggested_fix as advice, not a mandate. \
Read each issue, understand what actually went wrong, and produce a \
genuinely better plan. Don't just patch the literal complaint; reconsider \
the affected bullet(s) properly, and don't introduce new problems while \
fixing the old ones.

Return valid JSON matching the schema."""

_SECTION_WRITING_PROMPT = """\
You are writing tailored resume bullets for ONE experience section.

## What you receive

- section_plan: the plan for this section, including story_arc and a \
bullet_plan for each bullet position
- experience_story: the rich reconstructed narrative of what the candidate \
actually did in this role — your PRIMARY SOURCE for writing material

## How to write each bullet

For each bullet_plan, the framing_guidance field is your primary instruction. \
It tells you EXACTLY what to do:

- What facts to KEEP from the original bullet
- What to REMOVE (project names, internal jargon, wrong-role signals)
- What to FOREGROUND (the aspect that matters for the target role)
- What VOCABULARY to use
- Whether to use the original as a starting point or write fresh from story material

**Follow the framing_guidance literally.** If it says "Remove X", remove X. \
If it says "Foreground Y", make Y the leading element. If it says "Do NOT \
use the original bullet", write entirely from the experience story.

## Writing quality

- Each bullet should read as something a real professional wrote — \
specific, grounded, not generic
- Avoid buzzword stuffing ("leveraged", "utilized", "spearheaded" \
without substance)
- The bullet should clearly prove its claim to a reader who does not \
know the candidate
- Respect the layout_budget — match the original bullet's approximate length
- When framing_guidance says to change the angle, the revised bullet must \
feel genuinely different from the original — not a synonym swap

## Section coherence

- Follow the story_arc — bullets should build a coherent narrative
- Each bullet proves a different capability; together they paint a picture
- Read all bullet_plans before writing to ensure no redundancy

## Output

Return a JSON object with revised_bullets: a list of strings, one per \
bullet_plan, in the same order as the bullet_plans.

## If you are revising a previous attempt

If the user message includes a <previous_attempt_feedback> block, an editor \
already reviewed an earlier version of this section's bullets and found \
real problems, listed there with the editor's suggested_fix as advice, not \
a mandate. Write a genuinely better version — don't just patch the literal \
complaint, and don't introduce new problems while fixing the old ones.

Return valid JSON matching the schema."""

_AUDIT_PROMPT = """\
You are auditing a tailored resume against the original and the bullet plans.

Check for:
1. Fabrication: any claim not grounded in the experience stories or fact atoms
2. Claim fulfillment: does each bullet actually prove its assigned claim?
3. Framing integrity: did the framing stay within the fact boundary? \
Did it foreground the right aspects without overstating?
4. Identity coherence: does the resume still represent the same person? \
Would the reader form the correct impression of their background?
5. Section story: does each section follow its planned story arc?
6. Keyword stuffing: generic buzzwords added without evidence
7. Gaps honesty: are capabilities with "gap" evidence left unaddressed \
rather than implied?
8. Layout: did bullet lengths stay within budget?
9. Evidence integrity: for each bullet_plan, do its evidence_source_indices \
actually point to entries in fact_atoms whose own experience_index matches \
the bullet_plan's experience_index? An index that resolves to a DIFFERENT \
experience is a fabricated citation — flag it as critical, not a wording \
issue, even if the resulting bullet text itself reads as plausible.
10. Coverage: does every experience present in original_resume have at \
least one corresponding fact_atom and at least one bullet in the revised \
resume? An experience that silently lost all its evidence or all its \
bullets is critical, not a minor omission.
11. Strategy execution: does the revised resume actually deliver \
resume_strategy.resume_thesis? For each bullet_plan, is serves_capability \
either a real capability from resume_strategy.capability_strategies or the \
explicit "breadth_no_jd_match" marker? A bullet whose claim merely restates \
what the candidate is already strongest at — fluent, factually grounded, \
but not actually serving any capability the strategy decided to foreground \
or bridge — is a rephrase wearing a claim's clothing. Flag this even when \
nothing is fabricated and the writing reads well; the question is whether \
the bullet argues for THIS role per the strategy, not whether it sounds \
professional. Also check: when the strategy marked a capability "bridge" \
(adjacent evidence), does the corresponding bullet's evidence_strength \
still say "adjacent" with bridging language in framing_guidance, or was it \
quietly upgraded to "direct" with the domain gap glossed over? And: does \
any bullet claim a capability the strategy marked "omit_honest_gap" or \
"ask_candidate" — i.e. does the resume quietly violate a gap the strategy \
already decided to leave honest?

Return passed=true only if no critical issues found.
For each issue found, specify severity (critical/warning), the problem, \
and which pipeline step should be revisited to fix it.

Return valid JSON matching the schema."""


def _step_role_capability_inference(llm, jd_text: str, job_report: dict) -> RoleCapabilityInference:
    business_ctx = job_report.get("business_context", {})
    daily_workflow = job_report.get("daily_workflow", {})

    user_msg = (
        f"<business_context>\n"
        f"Why this role exists: {business_ctx.get('problem_solved', '')}\n"
        f"Summary: {business_ctx.get('summary', '')}\n"
        f"</business_context>\n\n"
        f"<daily_workflow>\n{json.dumps(daily_workflow, indent=2)}\n</daily_workflow>\n\n"
        f"<jd_text>\n{jd_text[:8000]}\n</jd_text>"
    )
    result = llm.complete_structured(
        system_prompt=_ROLE_CAPABILITY_INFERENCE_PROMPT,
        user_prompt=user_msg,
        response_schema=RoleCapabilityInference,
        max_tokens=3072,
        temperature=0.3,
    )
    if len(result.inferred_capabilities) > 20:
        logger.warning(
            "resume_tailor: role capability inference returned %d capabilities, "
            "truncating to 20", len(result.inferred_capabilities),
        )
        result.inferred_capabilities = result.inferred_capabilities[:20]
    return result


def _step_workstream_analysis(
    llm, jd_text: str, job_report: dict, inferred: RoleCapabilityInference,
) -> WorkstreamAnalysis:
    business_ctx = job_report.get("business_context", {})
    position_fn = job_report.get("position_function", {})
    daily_workflow = job_report.get("daily_workflow", {})
    skill_demands = job_report.get("underlying_skill_demands", [])

    user_msg = (
        f"<business_context>\n"
        f"Why this role exists: {business_ctx.get('problem_solved', '')}\n"
        f"Summary: {business_ctx.get('summary', '')}\n"
        f"</business_context>\n\n"
        f"<position_function>\n"
        f"Primary function: {position_fn.get('primary_function', '')}\n"
        f"Function mix: {position_fn.get('function_mix_description', '')}\n"
        f"</position_function>\n\n"
        f"<daily_workflow>\n{json.dumps(daily_workflow, indent=2)}\n</daily_workflow>\n\n"
        f"<underlying_skill_demands>\n{json.dumps(skill_demands, indent=2)}\n</underlying_skill_demands>\n\n"
        f"<inferred_capabilities>\n{json.dumps([c.model_dump() for c in inferred.inferred_capabilities], indent=2)}\n</inferred_capabilities>\n\n"
        f"<jd_text_reference>\n{jd_text[:4000]}\n</jd_text_reference>"
    )
    result = llm.complete_structured(
        system_prompt=_WORKSTREAM_PROMPT,
        user_prompt=user_msg,
        response_schema=WorkstreamAnalysis,
        max_tokens=8192,
        temperature=0.2,
    )
    _dedupe_workstream_analysis(result)
    return result


def _dedupe_workstream_analysis(analysis: WorkstreamAnalysis) -> None:
    """Collapse evidence_requirements that repeat the same capability across
    multiple workstreams into a single entry, and clean up the corresponding
    duplication risk inside workstreams[].capabilities.

    The prompt asks the model to canonicalize capabilities itself, but that's
    not reliable on its own — when the same capability text gets emitted as
    several separate evidence_requirements, downstream matching judges it
    independently each time and can hand back contradictory verdicts (e.g.
    "supporting" for one copy, "gap" for another) for what is really one
    question. This is the deterministic backstop.
    """
    merged: dict[str, EvidenceRequirement] = {}
    workstreams_by_key: dict[str, list[str]] = {}
    importance_rank = {"core": 0, "supporting": 1, "nice_to_have": 2}

    for req in analysis.evidence_requirements:
        key = req.capability.strip().lower()
        seen_workstreams = workstreams_by_key.setdefault(key, [])
        if req.workstream and req.workstream not in seen_workstreams:
            seen_workstreams.append(req.workstream)

        if key not in merged:
            merged[key] = req
            continue

        existing = merged[key]
        for item in req.evidence_checklist:
            if item not in existing.evidence_checklist:
                existing.evidence_checklist.append(item)
        if importance_rank.get(req.importance, 1) < importance_rank.get(existing.importance, 1):
            existing.importance = req.importance
        if existing.provenance == "inferred" and req.provenance == "stated":
            # A capability that was independently confirmed by both an
            # inferred guess and an explicit JD-grounded requirement is, at
            # that point, explicitly grounded — keep the stronger provenance.
            existing.provenance = "stated"
        logger.warning(
            "resume_tailor: merged duplicate evidence_requirement for "
            "capability=%r (workstream=%r into existing workstream=%r)",
            req.capability, req.workstream, existing.workstream,
        )

    for key, req in merged.items():
        workstreams = workstreams_by_key.get(key, [])
        if len(workstreams) > 1:
            req.reasoning = (
                f"{req.reasoning} (Serves multiple workstreams: "
                f"{', '.join(workstreams)}.)"
            ).strip()

    analysis.evidence_requirements = list(merged.values())

    # workstreams[].capabilities is a separate representation of the same
    # capabilities, kept for display/context. A capability legitimately
    # repeating ACROSS different workstreams' lists is correct (that's what
    # "this capability serves multiple workstreams" means) — but two things
    # are still bugs: the same capability appearing twice WITHIN one
    # workstream's own list, and a workstream's copy of a capability's
    # importance silently disagreeing with the canonical evidence_requirement
    # for the same capability (which is the value everything downstream
    # actually keys off). Both are fixed here, not re-judged.
    canonical_importance = {key: req.importance for key, req in merged.items()}
    for ws in analysis.workstreams:
        seen_in_workstream: set[str] = set()
        deduped_caps = []
        for cap in ws.capabilities:
            key = cap.capability.strip().lower()
            if key in seen_in_workstream:
                logger.warning(
                    "resume_tailor: removed duplicate capability within "
                    "workstream=%r: %r", ws.name, cap.capability,
                )
                continue
            seen_in_workstream.add(key)
            canonical = canonical_importance.get(key)
            if canonical is not None and cap.importance != canonical:
                cap.importance = canonical
            deduped_caps.append(cap)
        ws.capabilities = deduped_caps


def _step_story_reconstruction(llm, experiences: list[dict], experience_summary: str) -> list[ExperienceStory]:
    from pydantic import BaseModel as _BM

    class StoryOutput(_BM):
        experience_stories: list[ExperienceStory] = []

    exp_text = json.dumps(experiences, indent=2)[:15000]
    summary_section = ""
    if experience_summary:
        summary_section = (
            f"\n\n<experience_summary>\n"
            f"The following is a high-level summary of the candidate's background. "
            f"Use it to calibrate seniority level and scope when reconstructing "
            f"what this person actually did in each role.\n\n"
            f"{experience_summary[:3000]}\n"
            f"</experience_summary>"
        )

    result = llm.complete_structured(
        system_prompt=_STORY_PROMPT,
        user_prompt=f"<experiences>\n{exp_text}\n</experiences>{summary_section}",
        response_schema=StoryOutput,
        max_tokens=6144,
        temperature=0.3,
    )
    return result.experience_stories


def _step_fact_extraction(llm, stories: list[ExperienceStory]) -> list[FactAtom]:
    from pydantic import BaseModel as _BM

    class FactOutput(_BM):
        fact_atoms: list[FactAtom] = []

    stories_data = json.dumps([s.model_dump() for s in stories], indent=2)[:15000]

    result = llm.complete_structured(
        system_prompt=_FACT_EXTRACTION_PROMPT,
        user_prompt=f"<experience_stories>\n{stories_data}\n</experience_stories>",
        response_schema=FactOutput,
        max_tokens=6144,
        temperature=0.2,
    )

    expected_indices = {s.experience_index for s in stories}
    covered_indices = {f.experience_index for f in result.fact_atoms}
    missing = expected_indices - covered_indices
    if missing:
        logger.warning(
            "resume_tailor: fact extraction produced no fact_atoms for "
            "experience_index(es) %s — downstream evidence matching and "
            "bullet planning will have no real evidence for these experiences",
            sorted(missing),
        )

    return result.fact_atoms


def _step_evidence_matching(
    llm, workstream: WorkstreamAnalysis, facts: list[FactAtom],
    stories: list[ExperienceStory], fit_structured: dict,
) -> list[EvidenceMatch]:
    from pydantic import BaseModel as _BM

    class MatchOutput(_BM):
        evidence_matches: list[EvidenceMatch] = []

    indexed_facts = [
        {"index": i, **f.model_dump()} for i, f in enumerate(facts)
    ]

    stories_summary = [
        {
            "experience_index": s.experience_index,
            "employer": s.employer,
            "title": s.title,
            "narrative": s.narrative,
            "reconstruction_confidence": s.reconstruction_confidence,
        }
        for s in stories
    ]

    fit_summary = {}
    if fit_structured:
        fit_summary = {
            "strong_matches": fit_structured.get("strong_matches", []),
            "partial_matches": fit_structured.get("partial_matches", []),
            "gaps": fit_structured.get("gaps", []),
        }

    user_msg = (
        f"<evidence_requirements>\n{json.dumps([r.model_dump() for r in workstream.evidence_requirements], indent=2)}\n</evidence_requirements>\n\n"
        f"<fact_atoms>\n{json.dumps(indexed_facts, indent=2)[:10000]}\n</fact_atoms>\n\n"
        f"<experience_stories>\n{json.dumps(stories_summary, indent=2)[:6000]}\n</experience_stories>\n\n"
        f"<fit_report_context>\n{json.dumps(fit_summary, indent=2)[:3000]}\n</fit_report_context>"
    )
    result = llm.complete_structured(
        system_prompt=_MATCH_PROMPT,
        user_prompt=user_msg,
        response_schema=MatchOutput,
        max_tokens=8192,
        temperature=0.2,
    )
    _sanitize_evidence_sources(result.evidence_matches, facts)
    return result.evidence_matches


def _sanitize_evidence_sources(matches: list[EvidenceMatch], facts: list[FactAtom]) -> None:
    """Null out fact_atom_index on any source that doesn't belong to its
    claimed experience_index, or is out of range — the same fabrication
    failure mode as bullet planning, see _sanitize_evidence_citations."""
    for match in matches:
        for src in match.sources:
            if src.fact_atom_index is None:
                continue
            idx = src.fact_atom_index
            if not (0 <= idx < len(facts)) or facts[idx].experience_index != src.experience_index:
                logger.warning(
                    "resume_tailor: cleared fabricated fact_atom_index=%s for "
                    "capability=%r experience_index=%s",
                    idx, match.capability, src.experience_index,
                )
                src.fact_atom_index = None


def _step_resume_strategy(
    llm, workstream: WorkstreamAnalysis, matches: list[EvidenceMatch],
    stories: list[ExperienceStory], fit_structured: dict,
) -> ResumeStrategy:
    stories_summary = [
        {
            "experience_index": s.experience_index,
            "employer": s.employer,
            "title": s.title,
            "narrative": s.narrative,
            "reconstruction_confidence": s.reconstruction_confidence,
            "gaps": s.gaps,
        }
        for s in stories
    ]

    fit_summary = {}
    if fit_structured:
        fit_summary = {
            "strong_matches": fit_structured.get("strong_matches", []),
            "partial_matches": fit_structured.get("partial_matches", []),
            "gaps": fit_structured.get("gaps", []),
        }

    user_msg = (
        f"<evidence_requirements>\n{json.dumps([r.model_dump() for r in workstream.evidence_requirements], indent=2)}\n</evidence_requirements>\n\n"
        f"<evidence_matches>\n{json.dumps([m.model_dump() for m in matches], indent=2)}\n</evidence_matches>\n\n"
        f"<experience_stories>\n{json.dumps(stories_summary, indent=2)[:8000]}\n</experience_stories>\n\n"
        f"<fit_report_context>\n{json.dumps(fit_summary, indent=2)[:3000]}\n</fit_report_context>"
    )
    strategy = llm.complete_structured(
        system_prompt=_RESUME_STRATEGY_PROMPT,
        user_prompt=user_msg,
        response_schema=ResumeStrategy,
        max_tokens=6144,
        temperature=0.3,
    )
    _sanitize_capability_strategies(strategy, workstream.evidence_requirements)

    overflow = _capability_strategy_overflow(strategy)
    if overflow > 0:
        budget = sum(b.bullet_count_target for b in strategy.section_space_budget)
        committed = budget + overflow
        logger.warning(
            "resume_tailor: resume_strategy committed %d capabilities to "
            "foreground/bridge but only budgeted %d bullets total across "
            "section_space_budget — retrying once with feedback before "
            "this reaches bullet_planning",
            committed, budget,
        )
        feedback_msg = (
            f"{user_msg}\n\n"
            f"<previous_attempt_feedback>\n"
            f"Your previous attempt marked {committed} capabilities as "
            f"foreground or bridge, but section_space_budget only totals "
            f"{budget} bullets across all experiences. Re-prioritize: keep "
            f"the strongest {budget} (core importance > supporting/"
            f"nice_to_have, direct/strong-adjacent evidence > weaker, "
            f"provenance=stated > provenance=inferred) and downgrade the "
            f"rest to minimal_mention or omit_honest_gap.\n"
            f"</previous_attempt_feedback>"
        )
        retried = llm.complete_structured(
            system_prompt=_RESUME_STRATEGY_PROMPT,
            user_prompt=feedback_msg,
            response_schema=ResumeStrategy,
            max_tokens=6144,
            temperature=0.3,
        )
        _sanitize_capability_strategies(retried, workstream.evidence_requirements)
        remaining = _capability_strategy_overflow(retried)
        if remaining > 0:
            retried_budget = sum(b.bullet_count_target for b in retried.section_space_budget)
            logger.warning(
                "resume_tailor: resume_strategy still over budget after one "
                "retry (%d capabilities over a %d-bullet budget) — accepting "
                "as-is; downstream audit will surface any uncovered "
                "foreground/bridge capabilities as critical issues",
                retried_budget + remaining, retried_budget,
            )
        strategy = retried

    return strategy


def _capability_strategy_overflow(strategy: ResumeStrategy) -> int:
    """How many capability_strategies entries marked foreground/bridge exceed
    the total bullet_count_target across section_space_budget. <= 0 means
    the strategy's own commitments fit within its own stated budget."""
    budget = sum(b.bullet_count_target for b in strategy.section_space_budget)
    committed = sum(
        1 for cs in strategy.capability_strategies
        if cs.decision in ("foreground", "bridge")
    )
    return committed - budget


def _sanitize_capability_strategies(
    strategy: ResumeStrategy, requirements: list[EvidenceRequirement],
) -> None:
    """Make sure every evidence_requirement got a decision and no stray
    capability strings were invented — pure coverage/integrity check, not a
    re-judgment of which decision is right (that's the model's call)."""
    required = {r.capability for r in requirements}
    decided = {cs.capability for cs in strategy.capability_strategies}

    missing = required - decided
    for capability in missing:
        logger.warning(
            "resume_tailor: resume_strategy left capability=%r without a "
            "decision — defaulting to omit_honest_gap",
            capability,
        )
        strategy.capability_strategies.append(
            CapabilityStrategy(
                capability=capability,
                decision="omit_honest_gap",
                reasoning="No strategy decision was returned for this capability.",
            )
        )

    stray = decided - required
    if stray:
        logger.warning(
            "resume_tailor: resume_strategy referenced unknown capabilities "
            "not in evidence_requirements: %s",
            sorted(stray),
        )
        strategy.capability_strategies = [
            cs for cs in strategy.capability_strategies if cs.capability in required
        ]


def _step_bullet_planning(
    llm, workstream: WorkstreamAnalysis, matches: list[EvidenceMatch],
    facts: list[FactAtom], stories: list[ExperienceStory],
    experiences: list[dict], preferences: dict | None,
    strategy: ResumeStrategy, repair_feedback: list[AuditIssue] | None = None,
) -> list[SectionPlan]:
    from pydantic import BaseModel as _BM

    class PlanOutput(_BM):
        section_plans: list[SectionPlan] = []

    indexed_facts = [{"index": i, **f.model_dump()} for i, f in enumerate(facts)]

    stories_summary = [
        {
            "experience_index": s.experience_index,
            "employer": s.employer,
            "title": s.title,
            "narrative": s.narrative,
            "reconstruction_confidence": s.reconstruction_confidence,
        }
        for s in stories
    ]

    original_with_bullets = [
        {
            "index": i,
            "employer": e.get("employer", ""),
            "title": e.get("title", ""),
            "bullets": e.get("bullets", []),
        }
        for i, e in enumerate(experiences)
    ]

    pref_text = ""
    if preferences:
        pref_text = f"\n\n<preferences>\n{json.dumps(preferences, indent=2)}\n</preferences>"

    feedback_text = ""
    if repair_feedback:
        feedback_text = (
            f"\n\n<previous_attempt_feedback>\n"
            f"{json.dumps([i.model_dump() for i in repair_feedback], indent=2)}\n"
            f"</previous_attempt_feedback>"
        )

    user_msg = (
        f"<resume_strategy>\n{json.dumps(strategy.model_dump(), indent=2)}\n</resume_strategy>\n\n"
        f"<evidence_requirements>\n{json.dumps([r.model_dump() for r in workstream.evidence_requirements], indent=2)}\n</evidence_requirements>\n\n"
        f"<evidence_matches>\n{json.dumps([m.model_dump() for m in matches], indent=2)}\n</evidence_matches>\n\n"
        f"<fact_atoms>\n{json.dumps(indexed_facts, indent=2)[:10000]}\n</fact_atoms>\n\n"
        f"<experience_stories>\n{json.dumps(stories_summary, indent=2)[:6000]}\n</experience_stories>\n\n"
        f"<original_experiences>\n{json.dumps(original_with_bullets, indent=2)[:8000]}\n</original_experiences>"
        f"{pref_text}"
        f"{feedback_text}"
    )
    result = llm.complete_structured(
        system_prompt=_BULLET_PLANNING_PROMPT,
        user_prompt=user_msg,
        response_schema=PlanOutput,
        max_tokens=6144,
        temperature=0.3,
    )
    _sanitize_evidence_citations(result.section_plans, facts)
    _cap_evidence_strength_to_match(result.section_plans, matches)
    return result.section_plans


def _cap_evidence_strength_to_match(plans: list[SectionPlan], matches: list[EvidenceMatch]) -> None:
    """If a bullet declares which evidence_requirement it serves
    (serves_capability), its evidence_strength must not exceed what Step4
    already found for that capability.

    The prompt asks the model to apply Step4's verdict rather than re-decide
    it, but that's not reliable on its own — the model can quietly re-label
    "adjacent" evidence as "direct" and drop the required domain-bridging
    language (see patchcomment2.md). This is the deterministic backstop.
    """
    strength_rank = {"supporting": 0, "adjacent": 1, "direct": 2}
    match_by_capability = {m.capability: m.strength for m in matches}

    for plan in plans:
        for bp in plan.bullet_plans:
            cap = bp.serves_capability.strip()
            if cap == BREADTH_NO_JD_MATCH or cap not in match_by_capability:
                continue
            ceiling = match_by_capability[cap]
            if ceiling in ("gap", "weak"):
                logger.warning(
                    "resume_tailor: bullet exp_idx=%s bullet_idx=%s claims "
                    "capability=%r which evidence_matches rated %r — this "
                    "violates the 'do not design a bullet for gap/weak "
                    "capabilities' rule; downgrading evidence_strength to "
                    "supporting",
                    bp.experience_index, bp.bullet_index, cap, ceiling,
                )
                bp.evidence_strength = "supporting"
                continue
            if strength_rank.get(bp.evidence_strength, 0) > strength_rank.get(ceiling, 0):
                logger.warning(
                    "resume_tailor: downgraded evidence_strength %r -> %r for "
                    "exp_idx=%s bullet_idx=%s — evidence_matches only found "
                    "%r evidence for capability=%r",
                    bp.evidence_strength, ceiling, bp.experience_index,
                    bp.bullet_index, ceiling, cap,
                )
                bp.evidence_strength = ceiling


def _sanitize_evidence_citations(plans: list[SectionPlan], facts: list[FactAtom]) -> None:
    """Strip evidence_source_indices that cite a fact_atom from a different
    experience than the bullet they're attached to, or that are out of range.

    The model can fabricate plausible-looking indices when no real fact_atom
    exists for an experience (see the no-evidence case in
    _BULLET_PLANNING_PROMPT) — this is the deterministic backstop for that
    failure mode, since prompt wording alone doesn't reliably prevent it.
    """
    for plan in plans:
        for bp in plan.bullet_plans:
            valid = [
                idx for idx in bp.evidence_source_indices
                if 0 <= idx < len(facts) and facts[idx].experience_index == bp.experience_index
            ]
            if valid != bp.evidence_source_indices:
                logger.warning(
                    "resume_tailor: stripped fabricated evidence_source_indices "
                    "%s for exp_idx=%s bullet_idx=%s (valid indices for this "
                    "experience: %s)",
                    bp.evidence_source_indices, bp.experience_index, bp.bullet_index, valid,
                )
                bp.evidence_source_indices = valid
                if not valid:
                    bp.evidence_strength = "supporting"
                    note = (
                        "No fact-atom-level evidence available for this "
                        "experience — claim is derived directly from the "
                        "original bullet text only."
                    )
                    if note not in bp.boundary:
                        bp.boundary = f"{bp.boundary} {note}".strip()


def _step_write_bullets(
    llm, plans: list[SectionPlan], stories: list[ExperienceStory],
    structured_resume: dict, repair_feedback: list[AuditIssue] | None = None,
) -> tuple[str, list[str]]:
    """Returns (markdown, unresolved) — unresolved lists bullet_plan
    original_text values that could not be matched against the source
    document during assembly. The caller MUST surface these, not just log
    them — see _assemble_resume_markdown for why this matters."""
    from pydantic import BaseModel as _BM

    class SectionWriteOutput(_BM):
        revised_bullets: list[str] = []

    stories_by_idx = {s.experience_index: s for s in stories}
    all_revised: dict[int, list[tuple[str, str]]] = {}

    feedback_text = ""
    if repair_feedback:
        feedback_text = (
            f"\n\n<previous_attempt_feedback>\n"
            f"{json.dumps([i.model_dump() for i in repair_feedback], indent=2)}\n"
            f"</previous_attempt_feedback>"
        )

    for plan in plans:
        story = stories_by_idx.get(plan.experience_index)
        story_data = {
            "employer": story.employer if story else plan.employer,
            "title": story.title if story else plan.title,
            "narrative": story.narrative if story else "",
        }

        user_msg = (
            f"<section_plan>\n{json.dumps(plan.model_dump(), indent=2)}\n</section_plan>\n\n"
            f"<experience_story>\n{json.dumps(story_data, indent=2)}\n</experience_story>"
            f"{feedback_text}"
        )
        result = llm.complete_structured(
            system_prompt=_SECTION_WRITING_PROMPT,
            user_prompt=user_msg,
            response_schema=SectionWriteOutput,
            max_tokens=4096,
            temperature=0.3,
        )
        # revised_bullets is returned in the same order as plan.bullet_plans (per
        # _SECTION_WRITING_PROMPT), not in original-bullet order — pair by the
        # plan's own original_text rather than by position.
        originals = [bp.original_text for bp in plan.bullet_plans]
        all_revised[plan.experience_index] = list(zip(originals, result.revised_bullets))

    return _assemble_resume_markdown(structured_resume, all_revised)


def _assemble_resume_markdown(
    structured_resume: dict, revised_sections: dict[int, list[tuple[str, str]]]
) -> tuple[str, list[str]]:
    """Replace experience bullets in original markdown with revised ones.

    Matches by each bullet_plan's original_text rather than list position:
    bullet_planning can skip or reorder original bullets (e.g. for "gap"
    capabilities), so revised_bullets is not positionally aligned with the
    experience's original bullets list.

    bullet_planning is also allowed to plan fewer bullets than the experience
    originally had (it drops weak/redundant ones on purpose). Any original
    bullet that isn't referenced by a plan for an experience we touched is
    deleted here — otherwise it survives untouched next to its replacement
    and shows up as a near-duplicate bullet in the final resume.

    Safety rule: if ANY replacement in an experience's section fails to match
    (original_text isn't found verbatim in the document — e.g. the model
    merged two original bullets into one and the merged text doesn't appear
    as a literal substring), the deletion cleanup is skipped for that WHOLE
    experience. We can no longer tell which raw bullets are genuinely
    uncovered versus just textually mismatched with a failed plan, and a
    wrong guess there means silently losing content — worse than the
    near-duplicate a skipped cleanup might leave behind. Returns the list of
    original_text values that failed to match, so the caller can surface
    this as a real, visible problem rather than a log line nobody reads.
    """
    experiences = structured_resume.get("experiences", [])
    original_md = structured_resume.get("markdown", "")

    result_md = original_md
    unresolved: list[str] = []

    for exp_idx, pairs in revised_sections.items():
        if exp_idx >= len(experiences):
            continue

        covered_originals = set()
        section_had_failure = False
        for orig_text, revised_text in pairs:
            covered_originals.add(orig_text)
            if orig_text and orig_text in result_md:
                result_md = result_md.replace(orig_text, revised_text, 1)
            else:
                logger.warning(
                    "resume_tailor: could not locate original bullet text for "
                    "exp_idx=%s during assembly; leaving original content in "
                    "place rather than guessing: %r",
                    exp_idx, orig_text[:80],
                )
                unresolved.append(orig_text)
                section_had_failure = True

        if section_had_failure:
            continue

        for bullet in experiences[exp_idx].get("bullets", []):
            if bullet in covered_originals:
                continue
            new_md = _remove_bullet_line(result_md, bullet)
            if new_md != result_md:
                logger.info(
                    "resume_tailor: removed original bullet not covered by any "
                    "plan for exp_idx=%s: %r", exp_idx, bullet[:80],
                )
            result_md = new_md

    return result_md, unresolved


def _remove_bullet_line(markdown: str, bullet_text: str) -> str:
    """Strip the markdown line(s) containing a bullet that bullet_planning
    deliberately dropped, so it doesn't survive untouched in the final resume."""
    if not bullet_text or bullet_text not in markdown:
        return markdown
    lines = markdown.split("\n")
    kept = [line for line in lines if bullet_text not in line]
    if len(kept) == len(lines):
        return markdown
    return "\n".join(kept)


def _truncate_with_warning(label: str, text: str, limit: int) -> str:
    """Truncate text for an LLM prompt block, logging when it actually cuts
    content — silent truncation is how the audit ended up "blind" to most of
    workstream_analysis/resume_strategy once Step1.5 grew the capability set
    well past the budgets these were originally sized for."""
    if len(text) > limit:
        logger.warning(
            "resume_tailor: audit input <%s> truncated from %d to %d chars "
            "— audit will not see the full content",
            label, len(text), limit,
        )
        return text[:limit]
    return text


def _step_audit(
    llm, original_resume: dict, revised_markdown: str,
    plans: list[SectionPlan], workstream: WorkstreamAnalysis,
    facts: list[FactAtom], strategy: ResumeStrategy,
    unresolved_assembly: list[str] | None = None,
) -> AuditResult:
    indexed_facts = [
        {"index": i, "experience_index": f.experience_index, "context": f.context}
        for i, f in enumerate(facts)
    ]
    experience_count = len(original_resume.get("experiences", []))

    bullet_plans_json = json.dumps([p.model_dump() for p in plans], indent=2)
    strategy_json = json.dumps(strategy.model_dump(), indent=2)
    workstream_json = json.dumps(workstream.model_dump(), indent=2)

    user_msg = (
        f"<original_resume>\n{original_resume.get('markdown', '')[:8000]}\n</original_resume>\n\n"
        f"<revised_resume>\n{revised_markdown[:8000]}\n</revised_resume>\n\n"
        f"<bullet_plans>\n{_truncate_with_warning('bullet_plans', bullet_plans_json, 18000)}\n</bullet_plans>\n\n"
        f"<fact_atoms_index>\n{json.dumps(indexed_facts, indent=2)[:4000]}\n</fact_atoms_index>\n\n"
        f"<original_experience_count>{experience_count}</original_experience_count>\n\n"
        f"<resume_strategy>\n{_truncate_with_warning('resume_strategy', strategy_json, 16000)}\n</resume_strategy>\n\n"
        f"<workstream_analysis>\n{_truncate_with_warning('workstream_analysis', workstream_json, 20000)}\n</workstream_analysis>"
    )
    result = llm.complete_structured(
        system_prompt=_AUDIT_PROMPT,
        user_prompt=user_msg,
        response_schema=AuditResult,
        max_tokens=2048,
        temperature=0.2,
    )

    traceability_issues = _check_claim_traceability(plans, strategy)
    assembly_issues = _check_assembly_failures(unresolved_assembly or [])
    extra_issues = [*traceability_issues, *assembly_issues]
    if extra_issues:
        result.issues = [*result.issues, *extra_issues]
        if any(issue.severity == "critical" for issue in extra_issues):
            result.passed = False

    return result


def _check_assembly_failures(unresolved: list[str]) -> list[AuditIssue]:
    """Deterministic check: did any bullet_plan's original_text fail to match
    the source document during assembly?

    When this happens, _assemble_resume_markdown leaves the original bullet
    untouched rather than guessing whether it's safe to delete (see that
    function's docstring) — which means the intended revision for that
    bullet was silently discarded. A log warning is easy to miss; this turns
    it into a critical issue the repair loop can actually act on.
    """
    return [
        AuditIssue(
            severity="critical",
            issue=(
                "A planned bullet's original_text did not match the source "
                "document during assembly, so its revision was discarded and "
                "the original bullet was left in place instead. This is often "
                "caused by a plan that merges multiple original bullets into "
                "one (the merged text never appears verbatim in the source) — "
                f"the original_text in question: {orig_text[:200]!r}"
            ),
            affected_bullet=orig_text[:200],
            suggested_fix=(
                "Write an original_text that matches a single original bullet "
                "exactly, verbatim. If the intent is to combine the evidence "
                "from multiple original bullets into one stronger bullet, do "
                "that through framing_guidance and claim — but original_text "
                "must still point to just the one original bullet whose "
                "position this plan is replacing."
            ),
            fix_step="bullet_planning",
        )
        for orig_text in unresolved
    ]


def _check_claim_traceability(
    plans: list[SectionPlan], strategy: ResumeStrategy,
) -> list[AuditIssue]:
    """Deterministic check: did bullet planning actually execute
    resume_strategy, instead of quietly re-deciding it?

    An LLM-only audit isn't reliable here because nothing forces it to check
    claim-to-strategy mapping specifically — see patchcomment2.md: Step5 can
    quietly fall back to describing whatever the candidate is naturally
    strongest at, in fluent language that reads fine on its own, with no
    factual fabrication for the LLM audit to catch. This checks three
    distinct failure modes:

    1. A bullet claims a capability that isn't in the strategy at all
       (not even marked breadth_no_jd_match) — untraceable.
    2. A bullet claims a capability the strategy explicitly said NOT to
       claim (omit_honest_gap / ask_candidate) — strategy violation.
    3. A capability the strategy said to foreground/bridge has zero
       bullets — strategy silently dropped.
    """
    issues: list[AuditIssue] = []
    by_capability = {cs.capability: cs for cs in strategy.capability_strategies}
    should_be_claimed = {
        cs.capability for cs in strategy.capability_strategies
        if cs.decision in ("foreground", "bridge")
    }
    should_not_be_claimed = {
        cs.capability for cs in strategy.capability_strategies
        if cs.decision in ("omit_honest_gap", "ask_candidate")
    }
    cited_capabilities: set[str] = set()

    for plan in plans:
        for bp in plan.bullet_plans:
            cap = bp.serves_capability.strip()
            if cap == BREADTH_NO_JD_MATCH:
                continue
            if cap in should_not_be_claimed:
                decision = by_capability[cap].decision
                issues.append(AuditIssue(
                    severity="critical",
                    issue=(
                        f"Bullet claims capability {cap!r}, but resume_strategy "
                        f"decided '{decision}' for it — this bullet contradicts "
                        "a strategic decision that was already made, not a "
                        "fresh judgment call."
                    ),
                    affected_bullet=bp.claim,
                    suggested_fix=(
                        f"Remove this claim or replace it with a capability "
                        "resume_strategy marked 'foreground' or 'bridge' that "
                        "doesn't yet have a bullet."
                    ),
                    fix_step="bullet_planning",
                ))
            elif cap not in by_capability:
                issues.append(AuditIssue(
                    severity="critical",
                    issue=(
                        f"Bullet claim does not trace to any capability in "
                        f"resume_strategy and isn't marked '{BREADTH_NO_JD_MATCH}': "
                        f"serves_capability={cap!r}, claim={bp.claim!r}. This "
                        "bullet may be a rephrase of the original rather than "
                        "evidence designed for this role."
                    ),
                    affected_bullet=bp.claim,
                    suggested_fix=(
                        "Set serves_capability to an exact capability string from "
                        f"resume_strategy.capability_strategies, or to "
                        f"'{BREADTH_NO_JD_MATCH}' if this bullet is intentionally "
                        "not JD-targeted."
                    ),
                    fix_step="bullet_planning",
                ))
            else:
                cited_capabilities.add(cap)

    for capability in should_be_claimed - cited_capabilities:
        decision = by_capability[capability].decision
        issues.append(AuditIssue(
            severity="critical",
            issue=(
                f"resume_strategy marked {capability!r} as '{decision}' but no "
                "bullet claims it. The resume is silently dropping a capability "
                "the strategy decided was worth foregrounding."
            ),
            affected_bullet=None,
            suggested_fix=(
                "Add a bullet that claims this capability per the strategy's "
                "reasoning, or revisit the strategy if there genuinely isn't "
                "evidence to support it."
            ),
            fix_step="bullet_planning",
        ))

    return issues


def _attempt_repair(
    llm, audit: AuditResult, workstream: WorkstreamAnalysis,
    matches: list[EvidenceMatch], facts: list[FactAtom],
    stories: list[ExperienceStory], experiences: list[dict],
    preferences: dict | None, strategy: ResumeStrategy,
    structured_resume: dict, section_plans: list[SectionPlan],
) -> tuple[list[SectionPlan], str, AuditResult] | None:
    """One bounded repair pass.

    Re-runs the earliest pipeline step a critical audit issue points to, with
    the audit's findings passed as feedback — not as a literal patch
    instruction, the model re-decides how to fix it, the same way an editor
    sends a draft back with comments rather than rewriting it themselves.
    Then re-runs everything downstream of that step once and re-audits.

    Runs at most once per resume_tailor invocation. If the second audit
    still fails, that result is accepted and surfaced as-is — this is the
    minimal-version scope, not an unbounded loop. Only fix_step in
    {bullet_planning, writing} is handled here; issues whose fix_step points
    further upstream (workstream / fact_extraction / evidence_matching /
    strategy) are surfaced but not auto-repaired in this version.
    """
    critical = [i for i in audit.issues if i.severity == "critical"]
    if not critical:
        return None

    fix_steps = {i.fix_step for i in critical}
    repairable = {"bullet_planning", "writing"} & fix_steps
    if not repairable:
        logger.warning(
            "resume_tailor: audit failed with fix_step(s) %s outside repair "
            "loop scope (bullet_planning/writing only) — accepting result "
            "without a repair attempt",
            sorted(fix_steps),
        )
        return None

    logger.info(
        "resume_tailor: attempting one repair pass for fix_step(s) %s",
        sorted(repairable),
    )

    if "bullet_planning" in repairable:
        new_plans = _step_bullet_planning(
            llm, workstream, matches, facts, stories, experiences,
            preferences, strategy, repair_feedback=critical,
        )
        new_markdown, new_unresolved = _step_write_bullets(
            llm, new_plans, stories, structured_resume,
        )
    else:
        new_plans = section_plans
        new_markdown, new_unresolved = _step_write_bullets(
            llm, section_plans, stories, structured_resume, repair_feedback=critical,
        )

    new_audit = _step_audit(
        llm, structured_resume, new_markdown, new_plans, workstream, facts, strategy,
        new_unresolved,
    )
    return new_plans, new_markdown, new_audit


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
