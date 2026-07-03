"""
Handler for agent.candidate_story_build tasks.

Execution mode: OPENCLAW (investigation) + direct LLM call (structuring)
Agent: candidate-story-agent
Skill: candidate-story-v1

Flow:
  1. Read run/task from Postgres; resolve candidate profile
  2. Build AgentInvocationSpec
  3. Build payload (structured_resume + output path) → write input.json
  4. Create agent_invocation record
  5. Call OpenClawRuntime.invoke(spec) — agent conducts a free-form
     Hiring-Manager/Candidate-Advocate investigation per experience and
     writes investigation_transcript.json (no structured schema; real
     web_search only when needed to answer a specific question)
  6. Update agent_invocation with exit_code / timing
  7. Read output_manifest.json → parse StoryBankManifest
  8. Read investigation_transcript.json
  9. Structuring step (non-agentic): a direct LLMClient.complete_structured()
     call turns the transcript(s) into the final story schema. This is a
     plain LLM call, not an OpenClaw agent — it only extracts and classifies
     from what's already in the transcript, it cannot invent research.
  10. Anti-fabrication check: drop any research_basis entry whose cited URL
      does not literally appear in the source transcript text
  11. Minimal content validation, then persist stories to candidate_story_bank
  12. Mark task succeeded
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid as _uuid
from pathlib import Path

from pydantic import ValidationError

from packages.contracts.agents.invocation import AgentBudget
from packages.contracts.agents.manifests import StoryBankManifest
from packages.contracts.api.runs import CandidateStoryBuildInput
from packages.contracts.reports.candidate_story import (
    CandidateStory,
    InvestigationTranscript,
    StoryNarrativeOutput,
    StorySkeletonOutput,
)
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.domain.agent_jobs.planner import build_invocation_spec, build_task_input
from packages.infrastructure.agent_runtime.openclaw import create_runtime
from packages.infrastructure.db.repositories import (
    AgentInvocationRepository,
    ArtifactRepository,
    ProfileRepository,
    RunRepository,
    StoryBankRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = os.environ.get("AGENT_ARTIFACTS_DIR", "/app/data/agent_artifacts")

_VALID_EVIDENCE_TYPES = frozenset(
    {
        "observed_fact",
        "strongly_implied",
        "plausible_inference",
        "industry_archetype",
        "candidate_question",
    }
)

_NARRATIVE_SAFE_EVIDENCE_TYPES = frozenset({"observed_fact", "strongly_implied"})

_STRUCTURING_MODEL = os.environ.get("CANDIDATE_STORY_STRUCTURING_MODEL", "gpt-5.4-mini")

_MAX_PAYLOAD_CHARS = 400_000

_URL_RE = re.compile(r"https?://[^\s\"')\]]+")


def handle_story_bank_build(env: TaskEnvelope) -> dict:
    """Entry point for agent.candidate_story_build tasks."""
    logger.info("story_bank_build: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    # ------------------------------------------------------------------
    # Step 1: Read run context and resolve profile
    # ------------------------------------------------------------------
    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        input_snapshot = run.input_snapshot_json or {}
        workspace_id = env.workspace_id

    try:
        inp = CandidateStoryBuildInput.model_validate(input_snapshot)
    except ValidationError as exc:
        logger.error("story_bank_build: invalid input_snapshot: %s", exc)
        _mark_needs_review(
            env,
            invocation_id="",
            reason=f"Invalid candidate_story_build input: {exc}",
            error_code="INVALID_INPUT",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    profile_id = None
    structured_resume = None
    profile_markdown = ""

    with get_session() as session:
        profile_repo = ProfileRepository(session)
        profile = (
            profile_repo.get_by_id(inp.profile_id)
            if inp.profile_id
            else profile_repo.get_for_workspace(workspace_id)
        )
        if profile:
            # Extract all needed values inside the session to avoid detached-instance errors
            profile_id = profile.id
            structured_resume = profile.structured_resume_json
            profile_markdown = (structured_resume or {}).get("markdown", "")

    if not profile_id:
        _mark_needs_review(
            env, invocation_id="",
            reason="No candidate profile found. Import your resume first.",
            error_code="MISSING_PROFILE",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    if not structured_resume or not structured_resume.get("experiences"):
        _mark_needs_review(
            env, invocation_id="",
            reason="Profile has no structured resume with experiences.",
            error_code="MISSING_STRUCTURED_RESUME",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 2: Build AgentInvocationSpec
    # ------------------------------------------------------------------
    budget = AgentBudget(
        max_tool_calls=inp.max_tool_calls,
        timeout_seconds=inp.timeout_seconds,
    )

    invocation_id = str(_uuid.uuid4())

    spec = build_invocation_spec(
        run_id=env.run_id,
        task_id=env.task_id,
        workspace_id=workspace_id,
        task_type=env.task_type,
        attempt=env.attempt,
        artifacts_base_dir=_ARTIFACTS_DIR,
        payload=input_snapshot,
        budget=budget,
        invocation_id=invocation_id,
    )

    # ------------------------------------------------------------------
    # Step 3: Build input.json and write to artifact volume
    # ------------------------------------------------------------------
    run_dir = Path(_ARTIFACTS_DIR) / env.run_id / env.task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    enriched_payload = {
        **input_snapshot,
        "profile_id": profile_id,
        "structured_resume": structured_resume,
        "profile_markdown": profile_markdown[:6000],
        "budget": {
            "max_tool_calls": inp.max_tool_calls,
        },
        "expected_output_paths": {
            "investigation_transcript": str(run_dir / "investigation_transcript.json"),
        },
    }

    task_input = build_task_input(
        spec=spec,
        task_type=env.task_type,
        payload=enriched_payload,
        budget=budget,
    )

    input_json_path = Path(spec.input_spec_path)
    input_json_path.write_text(task_input.model_dump_json(indent=2))
    logger.info("story_bank_build: wrote input.json to %s", input_json_path)

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
            output_manifest_uri=spec.output_manifest_path,
            id=invocation_id,
        )

        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="agent_invocation_created",
            message=f"Invocation {invocation_id} created (agent={spec.agent_id})",
        )

    # ------------------------------------------------------------------
    # Step 5: Invoke OpenClaw (investigation only — no structuring)
    # ------------------------------------------------------------------
    runtime = create_runtime()

    with get_session() as session:
        AgentInvocationRepository(session).mark_running(invocation_id)
        TaskEventRepository(session).append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="agent_invocation_started",
            message=f"OpenClaw invoked: agent={spec.agent_id} session={spec.session_key[:60]}",
        )

    result = runtime.invoke(spec)

    # ------------------------------------------------------------------
    # Step 6: Update invocation record
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
        AgentInvocationRepository(session).mark_finished(
            invocation_id,
            exit_code=result.exit_code,
            stdout_uri=stdout_path,
            stderr_uri=stderr_path,
            error_code="AGENT_EXIT_NONZERO" if result.exit_code != 0 else None,
            error_message=result.stderr[:500] if result.exit_code != 0 else None,
        )

    if result.usage:
        from packages.infrastructure.llm.usage_writer import persist_agent_usage
        persist_agent_usage(
            run_id=env.run_id, task_id=env.task_id,
            workspace_id=workspace_id, call_site="agent.candidate_story_build",
            model=result.usage.model, input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )

    if result.exit_code != 0 or result.timed_out:
        error_code = "AGENT_TIMEOUT" if result.timed_out else "AGENT_EXIT_NONZERO"
        reason = (
            f"Agent timed out after {spec.timeout_seconds}s"
            if result.timed_out
            else f"Agent exited with code {result.exit_code}"
        )
        if result.stderr:
            reason = f"{reason}: {result.stderr[:500]}"
        _mark_needs_review(env, invocation_id=invocation_id, reason=reason, error_code=error_code)
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 7: Read and parse output manifest
    # ------------------------------------------------------------------
    manifest_path = Path(spec.output_manifest_path)
    if not manifest_path.exists():
        _mark_needs_review(
            env, invocation_id=invocation_id,
            reason="output_manifest.json not found after agent completion",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    try:
        manifest = StoryBankManifest.model_validate(json.loads(manifest_path.read_text()))
    except Exception as exc:
        logger.exception("story_bank_build: failed to parse output_manifest.json: %s", exc)
        _mark_needs_review(
            env, invocation_id=invocation_id,
            reason=f"output_manifest.json parse error: {exc}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 8: Read investigation_transcript.json
    # ------------------------------------------------------------------
    transcript_path_str = manifest.artifact_paths.get("investigation_transcript")
    if not transcript_path_str:
        _mark_needs_review(
            env, invocation_id=invocation_id,
            reason="manifest missing 'investigation_transcript' artifact path",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    transcript_path = Path(transcript_path_str)
    if not transcript_path.exists():
        _mark_needs_review(
            env, invocation_id=invocation_id,
            reason=f"investigation_transcript.json not found at {transcript_path}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    try:
        transcript = InvestigationTranscript.model_validate_json(transcript_path.read_text())
    except Exception as exc:
        _mark_needs_review(
            env, invocation_id=invocation_id,
            reason=f"investigation_transcript.json parse error: {exc}",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    if not transcript.experiences:
        _mark_needs_review(
            env, invocation_id=invocation_id,
            reason="investigation_transcript.json contains no experiences",
            error_code="EMPTY_TRANSCRIPT",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 9: Structuring (non-agentic direct LLM call)
    # ------------------------------------------------------------------
    try:
        stories = _step_structure_stories(structured_resume, transcript)
    except Exception as exc:
        logger.exception("story_bank_build: structuring step failed: %s", exc)
        _mark_needs_review(
            env, invocation_id=invocation_id,
            reason=f"structuring step failed: {exc}",
            error_code="STRUCTURING_FAILED",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 10: Anti-fabrication check on research_basis citations
    # ------------------------------------------------------------------
    transcript_by_ref = {e.experience_ref: e.transcript for e in transcript.experiences}
    stories = _filter_unverifiable_research_basis(stories, transcript_by_ref)

    stories_dicts = [s.model_dump() for s in stories]

    # ------------------------------------------------------------------
    # Step 11: Minimal content validation
    # ------------------------------------------------------------------
    validation_error = _validate_stories(stories_dicts)
    if validation_error:
        _mark_needs_review(
            env, invocation_id=invocation_id,
            reason=f"structured story content validation failed: {validation_error}",
            error_code="INVALID_STORY_CONTENT",
        )
        return {"status": "needs_review", "task_id": env.task_id}

    # ------------------------------------------------------------------
    # Step 12: Persist stories and artifacts
    # ------------------------------------------------------------------
    with get_session() as session:
        story_repo = StoryBankRepository(session)
        story_repo.upsert_stories(
            profile_id=profile_id,
            workspace_id=workspace_id,
            run_id=env.run_id,
            stories=stories_dicts,
        )

        artifact_repo = ArtifactRepository(session)
        for artifact_type, path_str in manifest.artifact_paths.items():
            artifact_repo.create(
                run_id=env.run_id,
                task_id=env.task_id,
                artifact_type=artifact_type,
                storage_uri=path_str,
                content_hash=_compute_file_sha256(path_str),
                metadata_json={"invocation_id": invocation_id, "profile_id": profile_id},
            )

        task_repo = TaskRepository(session)
        run_repo = RunRepository(session)
        event_repo = TaskEventRepository(session)

        task_repo.mark_succeeded(env.task_id)
        run_repo.complete(
            env.run_id,
            status="succeeded",
            result_summary={
                "profile_id": profile_id,
                "story_count": len(stories_dicts),
            },
        )
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=f"Story bank built: profile_id={profile_id}, stories={len(stories_dicts)}",
        )

    logger.info(
        "story_bank_build: task_id=%s succeeded, profile_id=%s stories=%d",
        env.task_id, profile_id, len(stories_dicts),
    )
    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "profile_id": profile_id,
        "story_count": len(stories_dicts),
    }


# ---------------------------------------------------------------------------
# Structuring step (non-agentic — plain LLM structured call, no tools)
# ---------------------------------------------------------------------------

_EVIDENCE_EXTRACTION_PROMPT = """\
You are extracting graded evidence from candidate investigation transcripts. \
You did not conduct these interviews — a separate investigator already did, \
playing two roles: a skeptical Hiring Manager asking pointed questions, and a \
Candidate Advocate answering honestly (including moments where it searched \
the web to resolve a specific question, moments where it made a calibrated \
judgment call without searching, and moments where it could not resolve a \
question at all).

## What you receive

One transcript per experience, each tagged with its own experience_ref, plus \
the original resume bullets for that experience (bullets_covered should \
reference these by index).

## Your only job: extract and grade, don't invent, don't write prose yet

Everything you write must trace back to something that is actually in the \
transcript. You are not investigating anything yourself — you have no tools \
and cannot verify anything beyond what the transcript already contains. You \
are NOT writing the final narrative in this step — that happens later, from \
only the highest-grade evidence you extract here. Your only job right now is \
extraction and honest grading.

## The five evidence_type grades — get this distinction right, it's the most \
important part of this task

- `observed_fact`: the Advocate answered directly from the bullet/resume \
  text. Set source_bullets to the relevant bullet indices.

- `strongly_implied`: the Advocate gave a STRICT LOGICAL inference — the \
  transcript shows reasoning of the form "X is not possible without also \
  having done Y" or equivalent deductive necessity. The test: could this be \
  false while the bullet is still true? If yes, it is not strongly_implied.

- `plausible_inference`: the Advocate answered using a CALIBRATED JUDGMENT \
  based on the candidate's tenure, seniority, title, or what's typical for \
  someone in that position — a likelihood judgment, not a logical necessity. \
  This is the grade most often confused with strongly_implied, because the \
  Advocate's phrasing is often just as confident-sounding ("very likely", \
  "the safest read is", "typically") for both. Do not go by tone — go by the \
  actual reasoning. If the transcript's reasoning is "given ~2 years in this \
  role, X is typical rather than delegated, because..." or "this is usually \
  how it's done, so probably..." — that is plausible_inference, regardless \
  of how confidently it reads. When genuinely unsure whether something is \
  strongly_implied or plausible_inference, choose plausible_inference — it \
  is the safer default.

- `industry_archetype`: the Advocate searched the web and answered with what \
  it found about typical/standard practice — not a confirmed fact about this \
  specific candidate. basis = a short description of what the search found. \
  Only cite a URL here if that exact URL appears in the transcript text you \
  were given — most searches in this transcript format will NOT have a \
  citable URL, because only the search query is preserved in the transcript, \
  not the results. That's fine — describe the finding without a URL rather \
  than inventing one.

- `candidate_question`: the Hiring Manager asked something the Advocate \
  never resolved.

## candidate_question and do_not_claim are not alternatives

For every point in the transcript where the Advocate could not resolve a \
question, always add it to `do_not_claim` (so the later narrative-writing \
step knows never to assert it). Additionally add it to `candidate_questions`, \
phrased as a direct question to ask the candidate, UNLESS asking them \
genuinely would not help — for example the Hiring Manager's question was \
itself speculative/hypothetical framing rather than a real, answerable \
information gap, or an equivalent question is already in the list. Do not \
silently drop an unresolved point into do_not_claim alone just because it \
seems minor — the default is both, not one or the other.

## research_basis

Only include an entry here if the transcript shows a real search happened \
(look for "[searched: ...]" markers or an explicit mention of what a search \
found) and describe what that search found. Never write a research_basis \
entry for a workstream whose transcript shows no search activity — an \
experience with no search in its transcript should have an empty \
research_basis, not a fabricated one. Do not include any URL that is not \
verbatim present in the transcript text.

## Coverage requirement (mandatory)

Your stories output MUST include at least one entry for EVERY experience_ref \
present in the input. A transcript that turned out short or thin still needs \
its own entry — even if that means fewer evidence_items, or an entry that's \
mostly candidate_question items if the interview mostly ended in unresolved \
questions. Do not skip an experience_ref just because another one is richer.

Before returning your answer, check: list every experience_ref from the \
input, and confirm each appears in at least one entry. If any are missing, \
go back and add entries for them.

## Splitting into stories within one experience

One experience may produce one story, or several, depending on how the \
transcript is organized — if the interview clearly moved through several \
distinct lines of questioning (different clusters of bullets, different \
threads), produce one story per thread. If it was one continuous line of \
questioning, produce one story. Let the transcript's own structure decide \
this — do not force a fixed number of stories per experience.

## story_id

A short, lowercase, hyphen-or-underscore slug identifying the workstream \
(e.g. `credit_spread_proxy_model`), unique within this candidate's story \
bank. Base it on what the story is actually about, not the experience_ref.

## workflow

`workflow` (inputs/methods/outputs/stakeholders) should only list things the \
transcript actually supports.
"""

_NARRATIVE_WRITING_PROMPT = """\
You are writing the final narrative for candidate story bank entries. A \
separate extraction step already read the full investigation transcripts and \
graded every claim by evidence strength — you are shown ONLY the \
highest-grade material (observed_fact and strongly_implied evidence: things \
either stated directly in the resume, or logically necessary given what's \
stated). Lower-grade material — calibrated guesses about what's typical, \
industry-typical assumptions, and anything the candidate never confirmed — \
has been deliberately withheld from you. If what you're given feels thin, \
that's not a mistake — it means that's genuinely all that's confirmed for \
this workstream.

## Your only job

Turn the given evidence into a readable, specific narrative (3-6 sentences) \
for each story. Write only what the evidence supports. Do not fill gaps with \
plausible-sounding detail, generic domain knowledge, or anything not present \
in what you were given — you have no way to know if it's true, and you were \
deliberately not shown the speculative material for exactly this reason.

A short, honest narrative that only covers what's actually confirmed is \
correct behavior, not a failure. Do not pad a thin story to sound more \
complete than it is.

## Guardrails

You are also given each story's `do_not_claim` list — statements the \
investigation explicitly determined should not be asserted. Do not write \
anything that contradicts or effectively restates one of these, even if the \
surrounding bullet text seems to suggest it.

## What you receive per story

workstream_title, the original resume bullets it covers (for terminology and \
phrasing, not as a substitute source when the evidence is thin), workflow, \
the observed_fact / strongly_implied evidence items, and the do_not_claim \
list.

## Output

One narrative per story, matched back by experience_ref + story_id together \
(story_id alone is not guaranteed unique across different experiences). \
Every story you are given must get exactly one narrative back.
"""


def _step_structure_stories(
    structured_resume: dict, transcript: InvestigationTranscript
) -> list[CandidateStory]:
    from packages.infrastructure.llm.client import LLMClient

    llm = LLMClient(model=_STRUCTURING_MODEL)
    logger.info("story_bank_build: structuring with model=%s", _STRUCTURING_MODEL)

    experiences_by_ref = {
        f"exp_{i}": exp for i, exp in enumerate(structured_resume.get("experiences", []))
    }

    payload = []
    for t in transcript.experiences:
        exp = experiences_by_ref.get(t.experience_ref, {})
        payload.append(
            {
                "experience_ref": t.experience_ref,
                "employer": t.employer or exp.get("employer", ""),
                "title": t.title or exp.get("title", ""),
                "bullets": exp.get("bullets", []),
                "transcript": t.transcript,
            }
        )
    bullets_by_ref = {p["experience_ref"]: p["bullets"] for p in payload}

    # Pass 1: extract and grade evidence. No narrative is written here.
    # NOTE: _MAX_PAYLOAD_CHARS truncation previously silently dropped whole
    # experiences off the end of richer transcripts (e.g. a "project
    # replication"-style Advocate can push combined payload well past 40k
    # chars) — this cap is a defensive backstop against a truly pathological
    # input, not a real model context limit, so it's set high.
    extraction_prompt = f"<experience_transcripts>\n{json.dumps(payload, indent=2)[:_MAX_PAYLOAD_CHARS]}\n</experience_transcripts>"
    skeleton_result: StorySkeletonOutput = llm.complete_structured(
        system_prompt=_EVIDENCE_EXTRACTION_PROMPT,
        user_prompt=extraction_prompt,
        response_schema=StorySkeletonOutput,
        max_tokens=16000,
        temperature=0.2,
    )

    expected_refs = {t.experience_ref for t in transcript.experiences}
    covered_refs = {s.experience_ref for s in skeleton_result.stories}
    missing = expected_refs - covered_refs
    if missing:
        logger.warning(
            "story_bank_build: extraction step produced no story for experience_ref(s) %s",
            sorted(missing),
        )

    if not skeleton_result.stories:
        return []

    # Pass 2: write narrative from only the highest-grade evidence. This call
    # never receives plausible_inference / industry_archetype / candidate_question
    # content, so it has no way to blend speculation into prose.
    narrative_input = []
    for skeleton in skeleton_result.stories:
        bullets = bullets_by_ref.get(skeleton.experience_ref, [])
        narrative_input.append(
            {
                "experience_ref": skeleton.experience_ref,
                "story_id": skeleton.story_id,
                "workstream_title": skeleton.workstream_title,
                "bullets": [b for i, b in enumerate(bullets) if i in skeleton.bullets_covered],
                "workflow": skeleton.workflow.model_dump(),
                "evidence": [
                    item.model_dump()
                    for item in skeleton.evidence_items
                    if item.evidence_type in _NARRATIVE_SAFE_EVIDENCE_TYPES
                ],
                "do_not_claim": skeleton.do_not_claim,
            }
        )

    narrative_prompt = f"<stories>\n{json.dumps(narrative_input, indent=2)[:_MAX_PAYLOAD_CHARS]}\n</stories>"
    narrative_result: StoryNarrativeOutput = llm.complete_structured(
        system_prompt=_NARRATIVE_WRITING_PROMPT,
        user_prompt=narrative_prompt,
        response_schema=StoryNarrativeOutput,
        max_tokens=4096,
        temperature=0.3,
    )
    narrative_by_key = {
        (n.experience_ref, n.story_id): n.narrative for n in narrative_result.narratives
    }

    missing_narratives = {
        (s.experience_ref, s.story_id) for s in skeleton_result.stories
    } - set(narrative_by_key)
    if missing_narratives:
        logger.warning(
            "story_bank_build: narrative step produced no narrative for (experience_ref, story_id) %s",
            sorted(missing_narratives),
        )

    return [
        CandidateStory(
            experience_ref=skeleton.experience_ref,
            story_id=skeleton.story_id,
            workstream_title=skeleton.workstream_title,
            bullets_covered=skeleton.bullets_covered,
            narrative=narrative_by_key.get((skeleton.experience_ref, skeleton.story_id), ""),
            workflow=skeleton.workflow,
            evidence_items=skeleton.evidence_items,
            candidate_questions=skeleton.candidate_questions,
            do_not_claim=skeleton.do_not_claim,
            research_basis=skeleton.research_basis,
        )
        for skeleton in skeleton_result.stories
    ]


def _filter_unverifiable_research_basis(
    stories: list[CandidateStory], transcript_by_ref: dict[str, str]
) -> list[CandidateStory]:
    """Drop research_basis entries whose cited URL isn't verbatim in the source transcript.

    The structuring step has no tools and can only see the transcript text —
    but nothing stops it from paraphrasing a plausible-looking citation the
    way the agent itself did in earlier testing. This is a cheap, mechanical
    backstop: any URL a research_basis entry cites must actually appear in
    the transcript for that story's experience_ref.
    """
    for story in stories:
        transcript_text = transcript_by_ref.get(story.experience_ref, "")
        kept = []
        for entry in story.research_basis:
            urls = _URL_RE.findall(entry)
            if urls and not all(u in transcript_text for u in urls):
                logger.warning(
                    "story_bank_build: dropping unverifiable research_basis entry "
                    "for story=%s (URL not found in transcript): %s",
                    story.story_id, entry,
                )
                continue
            kept.append(entry)
        story.research_basis = kept
    return stories


def _validate_stories(stories: list) -> str | None:
    """Minimal content check. Returns error message or None if valid."""
    if not stories:
        return "structuring step produced no stories"
    valid_evidence_types = _VALID_EVIDENCE_TYPES
    for i, s in enumerate(stories):
        if not s.get("experience_ref"):
            return f"story[{i}] missing experience_ref"
        if not s.get("narrative", "").strip():
            return f"story[{i}] has empty narrative"
        for item in s.get("evidence_items", []):
            etype = item.get("evidence_type")
            if etype and etype not in valid_evidence_types:
                return f"story[{i}] has invalid evidence_type: {etype!r}"
    return None


def _compute_file_sha256(path_str: str) -> str | None:
    try:
        digest = hashlib.sha256(Path(path_str).read_bytes()).hexdigest()
        return f"sha256:{digest}"
    except OSError:
        return None


def _mark_needs_review(
    env: TaskEnvelope,
    *,
    invocation_id: str,
    reason: str,
    error_code: str = "VALIDATOR_GATE_FAILED",
) -> None:
    with get_session() as session:
        task_repo = TaskRepository(session)
        run_repo = RunRepository(session)
        event_repo = TaskEventRepository(session)
        task_repo.mark_needs_review(
            env.task_id,
            error_code=error_code,
            error_message=reason[:500],
        )
        run_repo.complete(
            env.run_id,
            status="needs_review",
            result_summary={"error_code": error_code, "invocation_id": invocation_id},
        )
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_needs_review",
            message=reason,
        )
