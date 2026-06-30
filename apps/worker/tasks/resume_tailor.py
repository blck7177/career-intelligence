"""
Handler for resume_tailor tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a strategically tailored resume for a target job.

Pipeline (7 LLM calls):
  1.  Load all data (Job, JobReport, FitReport, Profile + StructuredResume)
  2.  (parallel) Workstream analysis — JobReport → evidence requirements
  3a. (parallel) Experience story reconstruction — bullets + role context → rich narratives
  3b. Fact atom extraction — stories → structured fact atoms
  4.  Evidence matching — requirements ↔ fact atoms (informed by stories)
  5.  Bullet planning — claim + evidence + framing + edit decision per bullet
  6.  Constrained writing — write bullets from plan + stories
  7.  Audit

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
    AuditResult,
    EvidenceMatch,
    EvidenceRequirement,
    ExperienceStory,
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
    # Steps 2 & 3a: Parallel — workstream analysis + story reconstruction
    # ------------------------------------------------------------------
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_ws = pool.submit(
            _step_workstream_analysis, llm, jd_text, job_report_structured
        )
        future_stories = pool.submit(
            _step_story_reconstruction, llm, experiences, experience_summary
        )
        workstream_analysis = future_ws.result()
        experience_stories = future_stories.result()

    _save_step("workstream_analysis", workstream_analysis)
    _save_step("experience_stories", experience_stories)

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
    # Step 5: Bullet planning — claim + evidence + framing per bullet
    # ------------------------------------------------------------------
    section_plans = _step_bullet_planning(
        llm, workstream_analysis, evidence_matches, fact_atoms,
        experience_stories, experiences, inp.preferences,
    )
    _save_step("bullet_plans", section_plans)

    # ------------------------------------------------------------------
    # Step 6: Constrained writing — write bullets from plan + stories
    # ------------------------------------------------------------------
    revised_markdown = _step_write_bullets(
        llm, section_plans, experience_stories, structured_resume
    )
    _save_step("revised_markdown", {"markdown": revised_markdown})

    # ------------------------------------------------------------------
    # Step 7: Audit
    # ------------------------------------------------------------------
    audit = _step_audit(
        llm, structured_resume, revised_markdown, section_plans, workstream_analysis
    )
    _save_step("audit", audit)

    draft = ResumeTailorDraft(
        workstream_analysis=workstream_analysis,
        experience_stories=experience_stories,
        fact_atoms=fact_atoms,
        evidence_matches=evidence_matches,
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
            "bullet_plans_count": bullet_count,
            "audit_passed": audit.passed,
            "audit_issues": len(audit.issues),
            "draft": draft.model_dump(),
        })
        task_repo.mark_succeeded(env.task_id)
        event_repo.append(
            task_id=env.task_id, run_id=env.run_id,
            event_type="task_succeeded",
            message=f"Resume tailored: {bullet_count} bullets planned, audit {'passed' if audit.passed else 'has issues'}",
        )

    logger.info("resume_tailor: task_id=%s succeeded", env.task_id)
    return {"status": "succeeded", "task_id": env.task_id}


# ---------------------------------------------------------------------------
# LLM step implementations
# ---------------------------------------------------------------------------

_WORKSTREAM_PROMPT = """\
You are transforming a pre-analyzed Job Intelligence Report into evidence \
requirements for resume tailoring.

## What you receive

A structured Job Intelligence Report that has already deeply analyzed this role:
- business_context: why the role exists and what problem it solves
- position_function: primary/secondary functions and their mix
- daily_workflow: inputs, analyses, outputs, and stakeholders
- underlying_skill_demands: each capability with demand type, importance, and evidence

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
that it primarily requires. Carry forward the demand_type and importance \
from the Job Report. A capability may serve multiple workstreams.

## Step 2: Derive evidence requirements

This is the core reasoning step. For each capability, derive what evidence \
must appear in a resume to prove the candidate has it.

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

## How to extract

1. Work through each story's claims list
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

## How to use the fit report

The fit_report_context provides profile-level matching (strong_matches, \
partial_matches, gaps). Use it as a starting hypothesis:
- If fit report says "strong match" on a capability, look for the specific \
fact atoms that support it — you may confirm or downgrade based on bullet-level evidence
- If fit report says "gap", check carefully — the profile-level analysis may \
have missed bullet-level evidence that the decomposition step surfaced
- Do not copy fit report conclusions. Re-evaluate at fact atom level.

Return valid JSON matching the schema."""

_BULLET_PLANNING_PROMPT = """\
You are designing the complete plan for each resume bullet — what it should \
prove, what evidence to use, and how to frame it for the target role.

## What you receive

- evidence_requirements: what the role needs proven, with importance levels \
and evidence_checklist
- evidence_matches: which capabilities have evidence, at what strength, \
with specific fact_atom sources
- fact_atoms: structured facts extracted from experience stories (indexed)
- experience_stories: the rich reconstructed narratives of what the candidate \
actually did — use for context and for finding replacement material
- original_experiences: the original resume structure (employer, title, bullets)

## Your task

For each experience section, produce:
1. A story_arc — what the hiring manager should believe after reading this section
2. A bullet_plan for each bullet position

## How to design a section story arc

A section is not a list of random accomplishments. It is an evidence portfolio \
that builds a specific impression.

Design the arc to follow this progression:
1. **Identity**: First bullet establishes WHO this person is in this role — \
their primary function and scope
2. **Core capability**: Next 1-2 bullets prove the most important capabilities \
the target role requires
3. **Execution/method**: Prove HOW they work — process, method, rigor
4. **Impact/stakeholder**: Prove their work MATTERED — who used it, what \
decisions it enabled
5. **Breadth** (if space): Secondary capabilities or governance evidence

Check your arc:
- Does the first bullet build the right identity for the target role?
- Are core capabilities proven before secondary ones?
- Does each bullet prove something DIFFERENT?
- Would the reader form the correct impression of this professional?

## How to plan each bullet

For each bullet position, make FIVE decisions:

### 1. Claim: what should this bullet prove?

Start from the ROLE'S needs, not from the original bullet text.

Look at evidence_matches:
- Which capability should this bullet position serve?
- Prioritize "core" capabilities over "supporting" or "nice_to_have"
- Do NOT assign a claim for a capability with strength "gap" or "weak"
- Do NOT duplicate claims across bullets

A claim is NOT a sentence. It is a capability statement:
  Good: "Can design automated analytical workflows that replace manual \
processes and are adopted by multiple teams"
  Bad: "Automated reporting workflow"

### 2. Evidence sources: what facts support this claim?

Find the fact atoms that best prove this claim. Reference them by index.
- Prefer fact atoms with confidence "stated" or "strongly_implied"
- An "inferred" fact atom can support but should not be the primary evidence
- Multiple fact atoms can combine to prove one claim

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

- Every claim must be backed by at least one fact_atom
- If evidence_strength is "adjacent", framing_guidance MUST explain how to \
bridge the domain difference
- boundary field: what the bullet must NOT claim, derived from fact atoms' boundaries
- Prefer fewer, stronger claims over many weak ones

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

Return passed=true only if no critical issues found.
For each issue found, specify severity (critical/warning), the problem, \
and which pipeline step should be revisited to fix it.

Return valid JSON matching the schema."""


def _step_workstream_analysis(llm, jd_text: str, job_report: dict) -> WorkstreamAnalysis:
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
        f"<jd_text_reference>\n{jd_text[:4000]}\n</jd_text_reference>"
    )
    return llm.complete_structured(
        system_prompt=_WORKSTREAM_PROMPT,
        user_prompt=user_msg,
        response_schema=WorkstreamAnalysis,
        max_tokens=4096,
        temperature=0.2,
    )


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
        max_tokens=4096,
        temperature=0.2,
    )
    return result.evidence_matches


def _step_bullet_planning(
    llm, workstream: WorkstreamAnalysis, matches: list[EvidenceMatch],
    facts: list[FactAtom], stories: list[ExperienceStory],
    experiences: list[dict], preferences: dict | None,
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

    user_msg = (
        f"<evidence_requirements>\n{json.dumps([r.model_dump() for r in workstream.evidence_requirements], indent=2)}\n</evidence_requirements>\n\n"
        f"<evidence_matches>\n{json.dumps([m.model_dump() for m in matches], indent=2)}\n</evidence_matches>\n\n"
        f"<fact_atoms>\n{json.dumps(indexed_facts, indent=2)[:10000]}\n</fact_atoms>\n\n"
        f"<experience_stories>\n{json.dumps(stories_summary, indent=2)[:6000]}\n</experience_stories>\n\n"
        f"<original_experiences>\n{json.dumps(original_with_bullets, indent=2)[:8000]}\n</original_experiences>"
        f"{pref_text}"
    )
    result = llm.complete_structured(
        system_prompt=_BULLET_PLANNING_PROMPT,
        user_prompt=user_msg,
        response_schema=PlanOutput,
        max_tokens=6144,
        temperature=0.3,
    )
    return result.section_plans


def _step_write_bullets(
    llm, plans: list[SectionPlan], stories: list[ExperienceStory],
    structured_resume: dict,
) -> str:
    from pydantic import BaseModel as _BM

    class SectionWriteOutput(_BM):
        revised_bullets: list[str] = []

    stories_by_idx = {s.experience_index: s for s in stories}
    all_revised: dict[int, list[tuple[str, str]]] = {}

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
) -> str:
    """Replace experience bullets in original markdown with revised ones.

    Matches by each bullet_plan's original_text rather than list position:
    bullet_planning can skip or reorder original bullets (e.g. for "gap"
    capabilities), so revised_bullets is not positionally aligned with the
    experience's original bullets list.
    """
    experiences = structured_resume.get("experiences", [])
    original_md = structured_resume.get("markdown", "")

    result_md = original_md
    for exp_idx, pairs in revised_sections.items():
        if exp_idx >= len(experiences):
            continue

        for orig_text, revised_text in pairs:
            if orig_text and orig_text in result_md:
                result_md = result_md.replace(orig_text, revised_text, 1)
            else:
                logger.warning(
                    "resume_tailor: could not locate original bullet text for "
                    "exp_idx=%s during assembly; skipping replacement: %r",
                    exp_idx, orig_text[:80],
                )

    return result_md


def _step_audit(
    llm, original_resume: dict, revised_markdown: str,
    plans: list[SectionPlan], workstream: WorkstreamAnalysis,
) -> AuditResult:
    user_msg = (
        f"<original_resume>\n{original_resume.get('markdown', '')[:8000]}\n</original_resume>\n\n"
        f"<revised_resume>\n{revised_markdown[:8000]}\n</revised_resume>\n\n"
        f"<bullet_plans>\n{json.dumps([p.model_dump() for p in plans], indent=2)[:6000]}\n</bullet_plans>\n\n"
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
