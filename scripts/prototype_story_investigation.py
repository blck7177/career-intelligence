"""
Standalone prototype — NOT wired into the pipeline, NOT imported by any handler.

Tests the deterministic Hiring-Manager / Candidate-Advocate investigation loop
discussed in dev_note/career/phase16-candidate/ before committing to rewiring
apps/worker/tasks/story_bank_build.py and retiring the candidate-story-agent
OpenClaw registration.

Architecture (six bounded LLM nodes, each a plain LLMClient.complete_structured()
call — no OpenClaw, no agent session):

  Node 0 — Orientation (once per experience): reads ALL bullets for one
    experience at once, splits them into workstreams, and for each workstream
    proposes a fixed set of investigation dimensions — named, stable sub-topics
    a thorough interviewer needs to cover. Dimensions are the shared vocabulary
    both later agents key their memory off of.

  Per round, within one workstream:
    Node 1 — HM Reflect: reads current dimension memory (open ones with their
      description, closed ones with their permanent note) plus only the most
      recent turn — not the full dialogue — and decides which dimensions just
      closed (resolved/fork) or whether a genuinely new one emerged. A closed
      dimension's note is written once and never revised. Whether the
      workstream is done is decided by whether any dimension remains open
      (plus a code-side hard coverage gate) — never by the model declaring
      "done" directly.
    Node 2 — HM Question: given the updated dimension memory, phrases ONE
      sharp question for the top of the priority queue.
    Node 3 — Candidate Advocate: answers as a project-replication attempt
      (stated / domain-reconstructed / genuine-fork), calibrated to
      candidate_context and to why this workstream exists, referencing its own
      memory of which dimensions it's already fully answered so it doesn't
      re-derive the same dead end twice. Searches via a direct Tavily call
      when its own domain knowledge is the uncertain part.

  Node 4 — Story Asset Synthesis (once per workstream, after its round loop
    ends): the actual deliverable this investigation exists to produce — not
    the transcript. Distills the full transcript into stated facts,
    reconstructed mechanisms, and genuine forks (kept in strictly separate
    buckets so a fork can never silently harden into a fact), plus capability
    signals, resume-bullet angles, interview-story angles, and direct
    open questions for the candidate.

  Node 5 — Reflection (once per experience, after all its workstreams):
    synthesizes the DELTA this experience added to the candidate's trajectory
    (not a snapshot) from the capability_signals already extracted by Node 4 —
    not from raw transcript text — so the stated/reconstructed distinction
    survives into what feeds forward as candidate_context for the next
    chronologically later experience.

Experiences are investigated oldest-first (see build_chronological_timeline)
so reconstruction of an earlier experience structurally cannot see anything
from a later one. Experiences/projects whose date ranges overlap (a side
project during a full-time role, two things done the same semester) are
explicitly annotated as concurrent rather than silently treated as sequential.

Run inside a container that has OPENAI_API_KEY and TAVILY_API_KEY (worker-agent
already has both):

    docker exec compose-worker-agent-1 sh -c "cd /app && python3 /tmp/prototype_story_investigation.py"

Output: prints progress, and writes {"experiences": [...], "trajectory": [...]}
to /tmp/prototype_transcripts.json for inspection. Each experience entry
carries both `transcript` (the raw investigation record, kept as an audit
trail) and `story_assets` (the structured, epistemically-tagged product).
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, "/app")
from packages.infrastructure.llm.client import LLMClient  # noqa: E402

_MODEL = os.environ.get("CANDIDATE_STORY_STRUCTURING_MODEL", "gpt-5.4-mini")
_TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
_MAX_ROUNDS_PER_WORKSTREAM = 10
_MAX_ROUNDS_PER_EXPERIENCE = 40  # coarse ceiling against pathological over-splitting only — not the per-workstream budget
_MAX_SEARCH_ATTEMPTS_PER_QUESTION = 2
_MAX_STALLED_ROUNDS = 3
_MAX_DIMENSION_STALLED_ROUNDS = 2


# ---------------------------------------------------------------------------
# Direct Tavily client — no OpenClaw
# ---------------------------------------------------------------------------


def tavily_search(query: str) -> str:
    """Real web search, direct API call. Returns a short text digest of results."""
    logger.info("  [tavily_search] %r", query)
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": _TAVILY_API_KEY,
            "query": query,
            "search_depth": "advanced",
            "max_results": 4,
            "include_answer": True,
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    lines = []
    if data.get("answer"):
        lines.append(f"Summary: {data['answer']}")
    for r in data.get("results", [])[:4]:
        lines.append(f"- {r.get('title', '')} ({r.get('url', '')}): {r.get('content', '')[:300]}")
    return "\n".join(lines) if lines else "(no results found)"


# ---------------------------------------------------------------------------
# Chronological timeline — pure data logic, no LLM. Experiences are
# investigated oldest-first so that reconstruction of an earlier experience
# structurally cannot see anything from a later one (LLMs are known to be
# unreliable at self-policing "don't reason backward in time" from an
# instruction alone, so the guarantee is enforced by what's in context, not
# by asking nicely). Education only carries a graduation_date, no start —
# entries are ordered by end/graduation date, the one date field both kinds
# reliably have.
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_resume_date(raw: str, *, end_of_period: bool) -> tuple[dt.date, bool]:
    """Parse a free-text resume date ("Feb 2023", "Present") into a sortable
    date. end_of_period picks the last vs. first day of the resolved month,
    so a bare "start_date" and "end_date" compare correctly even at month
    granularity. Returns (date, is_ongoing)."""
    s = (raw or "").strip()
    if not s or s.lower() in ("present", "current", "now", "ongoing"):
        return dt.date.today(), True

    year: Optional[int] = None
    month: Optional[int] = None
    for token in s.replace(",", "").split():
        if token.isdigit() and len(token) == 4:
            year = int(token)
        else:
            month = _MONTHS.get(token[:3].lower())

    if year is None:
        return dt.date.today(), True  # unparseable — don't guess, sort last

    if month is None:
        month = 12 if end_of_period else 1

    if end_of_period:
        day = 31 if month == 12 else (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day
    else:
        day = 1
    return dt.date(year, month, day), False


@dataclass
class TimelineEntry:
    kind: Literal["experience", "education"]
    ref: str
    label: str
    start: Optional[dt.date]
    end: dt.date
    is_ongoing: bool
    raw: dict


def build_chronological_timeline(structured_resume: dict) -> list[TimelineEntry]:
    """Merge experiences and education into one oldest-first timeline."""
    entries: list[TimelineEntry] = []

    for i, exp in enumerate(structured_resume.get("experiences", [])):
        start, _ = _parse_resume_date(exp.get("start_date", ""), end_of_period=False)
        end, ongoing = _parse_resume_date(exp.get("end_date", ""), end_of_period=True)
        entries.append(TimelineEntry(
            kind="experience", ref=f"exp_{i}",
            label=f"{exp.get('title', '')} @ {exp.get('employer', '')}",
            start=start, end=end, is_ongoing=ongoing, raw=exp,
        ))

    for i, edu in enumerate(structured_resume.get("education", [])):
        end, _ = _parse_resume_date(edu.get("graduation_date", ""), end_of_period=True)
        entries.append(TimelineEntry(
            kind="education", ref=f"edu_{i}",
            label=f"{edu.get('degree', '')}, {edu.get('institution', '')}",
            start=None, end=end, is_ongoing=False, raw=edu,
        ))

    entries.sort(key=lambda e: e.end)
    return entries


def annotate_concurrent_education(entries: list[TimelineEntry]) -> dict[str, str]:
    """For each experience, note which degrees hadn't graduated yet when it
    ended — inferred from date bracketing, never a fabricated start date."""
    notes: dict[str, str] = {}
    for entry in entries:
        if entry.kind != "experience":
            continue
        in_progress = [e.label for e in entries if e.kind == "education" and e.end > entry.end]
        if in_progress:
            notes[entry.ref] = f"This experience overlapped with still-in-progress study: {', '.join(in_progress)}."
    return notes


def annotate_concurrent_experiences(entries: list[TimelineEntry]) -> dict[str, str]:
    """For each experience, note which OTHER experiences/projects overlapped
    with it in time (start-to-end interval overlap). Sequential (end-date)
    processing order is only a linear approximation of the timeline — without
    this note, two things that actually happened in parallel (a side project
    during a full-time role, two things done the same semester) would have
    the earlier-processed one's reflection silently fed to the other as if it
    were a prior baseline, when neither could have informed the other."""
    notes: dict[str, str] = {}
    experiences = [e for e in entries if e.kind == "experience" and e.start is not None]
    for entry in experiences:
        overlaps = [
            e.label for e in experiences
            if e is not entry and e.start is not None
            and e.start <= entry.end and entry.start <= e.end
        ]
        if overlaps:
            notes[entry.ref] = (
                f"This happened concurrently with, not before or after: {', '.join(overlaps)}. "
                "Treat any candidate_context describing that experience as parallel information "
                "from the same period, not as an established baseline this experience built on."
            )
    return notes


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class InvestigationDimension(BaseModel):
    key: str = Field(description="Short stable snake_case slug, e.g. 'feature_selection_stopping_rule'. "
        "Referenced by this exact string in every later round — never renamed.")
    description: str = Field(description="1 sentence: what a thorough interviewer needs to nail down here.")


class Workstream(BaseModel):
    label: str = Field(description="Short name for this piece of work.")
    bullet_indices: list[int] = Field(description="Bullet indices belonging to this workstream.")
    situation_and_task: str = Field(
        description="2-4 sentences: why this work existed — the business/organizational "
        "need it served, who it was for, what the deliverable likely was. Concrete, not "
        "generic filler that could describe any team's work."
    )
    dimensions: list[InvestigationDimension] = Field(
        description="3-6 distinct sub-topics a thorough interviewer would need to nail down "
        "for this workstream, together covering everything in its bullets worth pressing on. "
        "Each must be a genuinely separate angle (e.g. target/benchmark definition, data "
        "sourcing, method/protocol, ownership boundary, validation approach) — not "
        "near-duplicates that would get asked about with the same underlying question."
    )


class ExperienceOrientation(BaseModel):
    workstreams: list[Workstream]


class DimensionUpdate(BaseModel):
    key: str = Field(description="Must exactly match an existing dimension key you were shown, "
        "or a key you're defining in new_dimensions this round.")
    status: Literal["resolved", "fork"]
    note: str = Field(description="Written once, permanently: the established fact (if resolved) "
        "or the named 2-3 branches (if fork). Never revised again after this call.")


class HMReflectDelta(BaseModel):
    assessment: str = Field(
        default="",
        description="Reasoning aid only, not persisted. What the most recent answer actually "
        "established vs. left generic, and whether it's internally consistent (no unflagged "
        "contradictions, no quietly-resolved forks). Empty/N-A if there's no answer yet.",
    )
    updates: list[DimensionUpdate] = Field(
        default_factory=list,
        description="Dimensions the most recent turn just closed. Do not include a dimension "
        "that's still open with nothing new to report. Do not re-touch an already-closed one.",
    )
    new_dimensions: list[InvestigationDimension] = Field(
        default_factory=list,
        description="Genuinely new dimensions the most recent turn revealed, not anticipated at "
        "orientation — should be rare. Never one that reworded an existing dimension's topic.",
    )
    reprioritize_to_front: str = Field(
        default="",
        description="Dimension key to jump the queue if the most recent turn revealed something "
        "urgent (e.g. an inconsistency) — empty if no reprioritization is needed.",
    )
    skip_bullets: list[int] = Field(
        default_factory=list,
        description="Bullet indices in this workstream too trivial/self-evident to need "
        "their own question. Must be paired with skip_reason.",
    )
    skip_reason: str = ""
    verify: bool = Field(
        default=False,
        description="True if independently checking the most recent answer via search would "
        "plausibly catch something wrong or add real information — not routine.",
    )
    verify_query: str = ""


class HMQuestion(BaseModel):
    question: str
    addresses_bullets: list[int] = Field(default_factory=list)


class DimensionClosure(BaseModel):
    key: str
    status: Literal["resolved", "fork"]


class AdvocateAnswer(BaseModel):
    answer: str
    closures: list[DimensionClosure] = Field(
        default_factory=list,
        description="Dimensions this answer fully closes from your side — no note needed, the "
        "reconstruction is already in `answer`. Only include one you're confident nothing more "
        "would come from asking again.",
    )
    needs_research: bool = Field(
        default=False,
        description="True if searching would sharpen this with real domain grounding, "
        "or would help resolve a genuine fork.",
    )
    search_query: str = ""


class StatedFact(BaseModel):
    fact: str
    source_bullets: list[int] = Field(default_factory=list)


class ReconstructedMechanism(BaseModel):
    mechanism: str
    confidence: Literal["strongly_implied", "plausible_reconstruction"] = Field(
        description="strongly_implied: the resume/context leaves little real room for "
        "another reading — near-certain, one step removed from a stated fact. "
        "plausible_reconstruction: a genuine domain-typical guess among several that "
        "could fit — real uncertainty remains, this is closer to a fork than a fact."
    )
    source_bullets: list[int] = Field(default_factory=list)


class GenuineForkAsset(BaseModel):
    question: str
    branches: list[str] = Field(description="2-3 concrete, mutually exclusive options — "
        "use this only when the possibilities can actually be enumerated.")
    source_bullets: list[int] = Field(default_factory=list)


class CandidateFollowUp(BaseModel):
    """An open gap that can't be reduced to 2-3 named branches — distinct from
    a fork. Use this when the honest answer is 'we don't know and can't even
    narrow it to a short list', not when you can actually name the options."""
    question: str
    why_it_matters: str = Field(description="Why this specific gap matters for "
        "understanding the work or the candidate's role in it — not generic curiosity.")
    source_bullets: list[int] = Field(default_factory=list)


class OutcomeSignal(BaseModel):
    """The Result in Situation/Task/Action/Result — what actually changed
    because of this work."""
    outcome: str = Field(description="What changed — quality, speed, risk, cost, "
        "adoption, a decision enabled, a problem that stopped recurring, etc.")
    confidence: Literal["stated", "strongly_implied", "plausible_reconstruction"]
    source_bullets: list[int] = Field(default_factory=list)


class KeyChallenge(BaseModel):
    challenge: str = Field(description="What made this genuinely hard, stated concretely — "
        "messy/ambiguous input, an unstable process, competing approaches with no obvious "
        "answer, a constraint the work had to fit inside, or a result that needed verifying "
        "before it could be trusted. Must be grounded in something already present in "
        "stated_facts/reconstructed_mechanisms/genuine_forks above, not a new invented "
        "difficulty — this field's job is to name the friction that's already implicit in "
        "that material, not to add drama.")
    source_bullets: list[int] = Field(default_factory=list)


class CapabilitySignal(BaseModel):
    capability: str = Field(description="Phrased at a cross-occupation register — the "
        "test: would someone working in operations, sales, or product management "
        "recognize this as a transferable competency, or does it only make sense inside "
        "this one domain? Put the domain-specific technique in `evidence`, not here.")
    epistemic_basis: Literal["stated", "strongly_implied", "plausible_reconstruction"] = Field(
        description="Whether this signal rests on a stated fact, a near-certain inference, "
        "or a domain-typical guess. Never round a plausible_reconstruction up to stated."
    )
    evidence: str = Field(description="The specific, domain-concrete claim this traces back to — not a vibe.")


class ResumeIngredient(BaseModel):
    """A component, not a finished sentence. Downstream (JD matching / resume
    writing) assembles these into an actual bullet — this layer's job is to
    hand over verified material, not commit to phrasing or tone."""
    action_fragment: str = Field(description="The core action, as a fragment — "
        "'reconciled two divergent expense-model schemas into one validation "
        "pipeline', not a full polished sentence with an implied subject and "
        "confident verb choice.")
    method_or_detail: str = Field(default="", description="The specific technique/tool/"
        "method that makes this credible and searchable, if one is established.")
    scope_or_scale: str = Field(default="", description="Size/scope qualifier, only if "
        "actually evidenced — leave blank rather than inventing a number.")
    confidence: Literal["stated", "strongly_implied"] = Field(
        description="Resume ingredients must rest on solid ground — never "
        "plausible_reconstruction or fork content. If nothing here clears that bar for "
        "a given action, leave it out rather than lowering the bar.")
    source_bullets: list[int] = Field(default_factory=list)


class WorkstreamStoryAsset(BaseModel):
    story_title: str
    candidate_role: str = Field(description="Ownership/scope synthesis, grounded only in "
        "stated_facts and reconstructed_mechanisms below.")
    core_actions: str = Field(description="3-5 sentence narrative of what they concretely did, "
        "written for interview-prep use. Grounded only in stated_facts/reconstructed_mechanisms.")
    stated_facts: list[StatedFact] = Field(default_factory=list)
    reconstructed_mechanisms: list[ReconstructedMechanism] = Field(default_factory=list)
    genuine_forks: list[GenuineForkAsset] = Field(default_factory=list)
    candidate_follow_ups: list[CandidateFollowUp] = Field(default_factory=list, description=
        "Open gaps that can't be reduced to 2-3 named branches — distinct from genuine_forks.")
    outcomes: list[OutcomeSignal] = Field(default_factory=list, description="The Result axis — "
        "what changed because of this work. Can be empty if the transcript genuinely never "
        "establishes one; do not manufacture an outcome to fill this.")
    key_challenges: list[KeyChallenge] = Field(default_factory=list, description="2-4 items. "
        "The difficulty/judgment points that make this worth telling as a story, not just "
        "a checklist of steps completed.")
    capability_signals: list[CapabilitySignal] = Field(default_factory=list)
    resume_ingredients: list[ResumeIngredient] = Field(default_factory=list, description=
        "Structured, atomic components usable later in a tailored resume bullet — never "
        "built from plausible_reconstruction or fork content.")
    interview_story_angles: list[str] = Field(default_factory=list, description="Framings usable "
        "later in a STAR-style interview answer — may draw on reconstructed content too, since "
        "this is rehearsal material, not a final claim.")
    open_questions_for_candidate: list[str] = Field(default_factory=list, description="Direct "
        "questions phrased for the candidate to actually answer, one per genuine_fork or "
        "candidate_follow_up worth resolving.")


class ExperienceReflection(BaseModel):
    reflection: str = Field(
        description="2-4 sentences: what CHANGED for this candidate as a result of this "
        "experience — the delta versus what was already established about them before it, not "
        "a snapshot. What they newly walked away knowing/comfortable with, and honestly, "
        "what's still a gap given their tenure/seniority here. Internal reconstruction "
        "aid and standalone trajectory record, not a capability or job-fit claim."
    )


# ---------------------------------------------------------------------------
# Persistent per-workstream memory — bounded state carried across rounds
# instead of re-deriving judgment from the full, ever-growing dialogue every
# round. Keyed by the dimension vocabulary Orientation defined once, so
# "have we already covered this" is a dict lookup, not a fuzzy text-similarity
# guess — the failure mode a free-text-list + dedup design (this script's
# previous iteration) could not reliably avoid. HM and Advocate each maintain
# their own dimension-state dict; the two are deliberately not merged
# (Advocate closing a dimension doesn't auto-close it for HM — HM still
# decides whether to press once more). A dimension's note is written exactly
# once, at the moment it closes, and never rewritten afterward — repeatedly
# having an LLM rewrite/consolidate the same memory content is a documented
# failure mode in its own right (arxiv 2605.12978), independent of the
# free-text-dedup problem this design also fixes.
# ---------------------------------------------------------------------------


@dataclass
class DimensionState:
    description: str = ""
    status: Literal["open", "resolved", "fork"] = "open"
    note: str = ""


@dataclass
class HMMemory:
    dimensions: dict[str, DimensionState] = field(default_factory=dict)
    priority_order: list[str] = field(default_factory=list)


@dataclass
class AdvocateMemory:
    dimensions: dict[str, DimensionState] = field(default_factory=dict)


def _init_dimension_states(dimensions: list[InvestigationDimension]) -> dict[str, DimensionState]:
    return {d.key: DimensionState(description=d.description) for d in dimensions}


def _apply_hm_delta(memory: HMMemory, delta: HMReflectDelta) -> None:
    for dim in delta.new_dimensions:
        if dim.key not in memory.dimensions:
            memory.dimensions[dim.key] = DimensionState(description=dim.description)
            memory.priority_order.append(dim.key)

    for upd in delta.updates:
        state = memory.dimensions.get(upd.key)
        if state is not None and state.status == "open":
            state.status = upd.status
            state.note = upd.note
            if upd.key in memory.priority_order:
                memory.priority_order.remove(upd.key)

    if delta.reprioritize_to_front and delta.reprioritize_to_front in memory.priority_order:
        memory.priority_order.remove(delta.reprioritize_to_front)
        memory.priority_order.insert(0, delta.reprioritize_to_front)


def _apply_advocate_closures(memory: AdvocateMemory, answer: AdvocateAnswer) -> None:
    for cl in answer.closures:
        state = memory.dimensions.get(cl.key)
        if state is not None and state.status == "open":
            state.status = cl.status


def _render_hm_memory(memory: HMMemory, skipped: dict[int, str]) -> str:
    lines = []
    for key, state in memory.dimensions.items():
        if state.status == "open":
            lines.append(f"[open] {key}: {state.description}")
        else:
            lines.append(f"[{state.status}] {key}: {state.note}")
    dims_block = "\n".join(lines) or "(none)"
    priority_block = "\n".join(memory.priority_order) or "(none — workstream is done)"
    skipped_block = "\n".join(f"- bullet {i}: {reason}" for i, reason in sorted(skipped.items())) or "(none)"
    return (
        f"<dimensions>\n{dims_block}\n</dimensions>\n"
        f"<priority_order>\n{priority_block}\n</priority_order>\n"
        f"<skipped_bullets_do_not_reraise>\n{skipped_block}\n</skipped_bullets_do_not_reraise>"
    )


def _render_advocate_memory(memory: AdvocateMemory) -> str:
    lines = []
    for key, state in memory.dimensions.items():
        if state.status == "open":
            lines.append(f"[open] {key}: {state.description}")
        else:
            lines.append(f"[{state.status}] {key}")
    block = "\n".join(lines) or "(none)"
    return f"<dimensions>\n{block}\n</dimensions>"


# ---------------------------------------------------------------------------
# Prompts — loaded from prototype_story_prompts/*.md (edit those files, not
# this script, to change prompt text). Kept as separate files so each node's
# prompt can be iterated on directly without navigating the orchestration code.
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent / "prototype_story_prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text().strip() + "\n"


_ORIENTATION_PROMPT = _load_prompt("orientation")
_HM_REFLECT_PLAN_PROMPT = _load_prompt("hm_reflect_plan")
_HM_QUESTION_PROMPT = _load_prompt("hm_question")
_ADVOCATE_PROMPT = _load_prompt("advocate")
_STORY_ASSET_PROMPT = _load_prompt("story_asset")
_REFLECTION_PROMPT = _load_prompt("reflection")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def orient_experience(
    llm: LLMClient,
    employer: str,
    title: str,
    start_date: str,
    end_date: str,
    bullets: list[str],
    candidate_context: str,
) -> ExperienceOrientation:
    bullets_block = "\n".join(f"{i}: {b}" for i, b in enumerate(bullets))
    user_prompt = (
        f"<experience>\nEmployer: {employer}\nTitle: {title}\n"
        f"Dates: {start_date} - {end_date}\nBullets:\n{bullets_block}\n</experience>\n"
        f"<candidate_context>\n{candidate_context}\n</candidate_context>"
    )
    return llm.complete_structured(
        system_prompt=_ORIENTATION_PROMPT,
        user_prompt=user_prompt,
        response_schema=ExperienceOrientation,
        max_tokens=3072,
        temperature=0.3,
    )


def synthesize_story_asset(
    llm: LLMClient,
    employer: str,
    title: str,
    workstream: Workstream,
    transcript: str,
    hm_memory: HMMemory,
    candidate_context: str,
) -> WorkstreamStoryAsset:
    dimension_summary = "\n".join(
        f"- [{s.status}] {key}: {s.note}" for key, s in hm_memory.dimensions.items() if s.status != "open"
    ) or "(none closed)"
    user_prompt = (
        f"<experience>\nEmployer: {employer}\nTitle: {title}\n</experience>\n"
        f"<workstream>\n{workstream.label}: {workstream.situation_and_task}\n</workstream>\n"
        f"<candidate_context>\n{candidate_context}\n</candidate_context>\n"
        f"<dimension_summary>\n{dimension_summary}\n</dimension_summary>\n"
        f"<full_investigation_transcript>\n{transcript}\n</full_investigation_transcript>"
    )
    return llm.complete_structured(
        system_prompt=_STORY_ASSET_PROMPT,
        user_prompt=user_prompt,
        response_schema=WorkstreamStoryAsset,
        max_tokens=3584,
        temperature=0.3,
    )


def investigate_workstream(
    llm: LLMClient,
    employer: str,
    title: str,
    start_date: str,
    end_date: str,
    bullets: list[str],
    workstream: Workstream,
    all_workstreams: list[Workstream],
    candidate_context: str,
    round_budget: int,
) -> tuple[str, int, WorkstreamStoryAsset]:
    ws_bullets_block = "\n".join(f"{i}: {bullets[i]}" for i in workstream.bullet_indices if i < len(bullets))
    other_workstreams_block = "\n".join(
        f"- {w.label}: {w.situation_and_task}" for w in all_workstreams if w.label != workstream.label
    )
    context = (
        f"<experience>\nEmployer: {employer}\nTitle: {title}\nDates: {start_date} - {end_date}\n</experience>\n"
        f"<current_workstream>\n{workstream.label}: {workstream.situation_and_task}\n"
        f"Bullets:\n{ws_bullets_block}\n</current_workstream>\n"
        + (
            f"<other_workstreams_in_this_experience>\n{other_workstreams_block}\n</other_workstreams_in_this_experience>\n"
            if other_workstreams_block
            else ""
        )
        + f"<candidate_context>\n{candidate_context}\n</candidate_context>"
    )

    transcript_lines: list[str] = []
    covered: set[int] = set()
    skipped: dict[int, str] = {}
    all_indices = set(workstream.bullet_indices)
    hm_memory = HMMemory(dimensions=_init_dimension_states(workstream.dimensions))
    hm_memory.priority_order = [d.key for d in workstream.dimensions]
    adv_memory = AdvocateMemory(dimensions=_init_dimension_states(workstream.dimensions))
    last_turn: Optional[tuple[str, str]] = None  # (question, answer) — most recent turn only
    # Set when a verify search fires; shown once to this round's Question call
    # and once more to next round's Reflect call, then dropped.
    verification_note = ""

    def uncovered() -> list[int]:
        return sorted(all_indices - covered - skipped.keys())

    def last_turn_block() -> str:
        if last_turn is None:
            return "(no questions asked yet — this is the first round)"
        q, a = last_turn
        return f"Hiring Manager: {q}\n\nCandidate Advocate: {a}"

    rounds_used = 0
    stalled_rounds = 0
    dimension_stalled_rounds = 0
    prior_top_dimension: Optional[str] = None
    for round_num in range(round_budget):
        rounds_used = round_num + 1

        reflect_extra = f"\n\n{verification_note}" if verification_note else ""
        delta = llm.complete_structured(
            system_prompt=_HM_REFLECT_PLAN_PROMPT,
            user_prompt=(
                f"{context}\n\n{_render_hm_memory(hm_memory, skipped)}\n\n"
                f"<most_recent_turn>\n{last_turn_block()}\n</most_recent_turn>{reflect_extra}"
            ),
            response_schema=HMReflectDelta,
            max_tokens=1536,
            temperature=0.4,
        )
        verification_note = ""
        _apply_hm_delta(hm_memory, delta)

        # A dimension closing is direct evidence of progress, same as new
        # bullet coverage — without this, stalled_rounds keeps accumulating
        # across a dimension boundary (e.g. 2 quiet rounds finishing off
        # dimension A followed immediately by dimension B's first, perfectly
        # normal round) and can kill a fresh dimension before it gets a fair
        # shot, since bullet coverage saturates early while dimension work
        # continues for many more rounds after.
        if delta.updates:
            stalled_rounds = 0

        for b in delta.skip_bullets:
            if b in all_indices:
                skipped[b] = delta.skip_reason or "(no reason given)"
        if delta.skip_bullets:
            logger.info("  [round %d] HM skips bullets %s: %s", round_num, delta.skip_bullets, delta.skip_reason)

        # Code-side hard gate: don't trust a self-assessed empty queue if
        # bullets in this workstream were never addressed or skipped.
        hard_uncovered = uncovered()
        if not hm_memory.priority_order and hard_uncovered:
            for i in hard_uncovered:
                key = f"bullet_{i}_uncovered"
                if key not in hm_memory.dimensions:
                    hm_memory.dimensions[key] = DimensionState(
                        description=f"Bullet {i} has not been addressed or explicitly skipped yet."
                    )
                    hm_memory.priority_order.append(key)

        if not hm_memory.priority_order:
            logger.info("  [round %d] Workstream '%s': done (coverage complete)", round_num, workstream.label)
            break

        # Code-side dimension stall detector: if the SAME dimension stays at
        # the front of the queue for several consecutive rounds despite being
        # asked about, HM's own judgment isn't closing it promptly enough —
        # observed pattern is a genuinely-forked dimension gets asked about
        # 2-3 times, each producing the same named branches, before HM
        # commits to closing it. Force it closed as a fork rather than
        # burning more rounds waiting for a commitment that isn't coming.
        # This is a narrower, more direct signal than the bullet-coverage
        # stall detector below — it fires on repetition of ONE dimension,
        # not on the coarser proxy of whether any bullet got newly tagged.
        current_top = hm_memory.priority_order[0]
        if current_top == prior_top_dimension:
            dimension_stalled_rounds += 1
        else:
            dimension_stalled_rounds = 0
        prior_top_dimension = current_top

        if dimension_stalled_rounds >= _MAX_DIMENSION_STALLED_ROUNDS:
            state = hm_memory.dimensions[current_top]
            logger.warning(
                "  [round %d] Dimension '%s' stalled — forcing fork closure after %d rounds without resolution",
                round_num, current_top, dimension_stalled_rounds,
            )
            state.status = "fork"
            state.note = state.note or (
                "Repeated pressing did not resolve this within the interview — treat as a "
                "genuine fork; only the candidate can confirm which branch is true."
            )
            hm_memory.priority_order.remove(current_top)
            dimension_stalled_rounds = 0
            prior_top_dimension = None
            stalled_rounds = 0
            if not hm_memory.priority_order:
                logger.info("  [round %d] Workstream '%s': done (coverage complete)", round_num, workstream.label)
                break

        if delta.verify and last_turn is not None:
            logger.info("  [round %d] HM verifies previous answer", round_num)
            verify_results = tavily_search(delta.verify_query)
            transcript_lines.append(f"[Hiring Manager independently verified: \"{delta.verify_query}\"]")
            transcript_lines.append(f"Verification found: {verify_results[:500]}")
            verification_note = f"[Verification of the most recent answer — searched \"{delta.verify_query}\": {verify_results[:500]}]"

        hm = llm.complete_structured(
            system_prompt=_HM_QUESTION_PROMPT,
            user_prompt=(
                f"{context}\n\n{_render_hm_memory(hm_memory, skipped)}\n\n"
                f"<most_recent_turn>\n{last_turn_block()}\n</most_recent_turn>"
                + (f"\n\n{verification_note}" if verification_note else "")
            ),
            response_schema=HMQuestion,
            max_tokens=768,
            temperature=0.4,
        )
        covered_before = len(covered)
        covered |= set(i for i in hm.addresses_bullets if i in all_indices)
        logger.info("  [round %d] Hiring Manager: %s", round_num, hm.question)
        transcript_lines.append(f"Hiring Manager: {hm.question}")

        if len(covered) > covered_before:
            stalled_rounds = 0
        else:
            stalled_rounds += 1
            if stalled_rounds >= _MAX_STALLED_ROUNDS:
                # Code-side safety net, independent of what the dimension
                # queue claims: no newly-covered bullet for several rounds in
                # a row means HM is re-asking the same ground without
                # progress. Stop rather than burn the whole experience's
                # round budget on one stuck point.
                logger.warning(
                    "  [round %d] Workstream '%s' stalled — %d rounds without new bullet "
                    "coverage, stopping", round_num, workstream.label, stalled_rounds,
                )
                transcript_lines.append(
                    f"[Stopped: no new bullet coverage for {stalled_rounds} consecutive "
                    f"rounds — remaining gaps ({uncovered()}) need direct candidate input, "
                    "not further pressing]"
                )
                break

        adv = llm.complete_structured(
            system_prompt=_ADVOCATE_PROMPT,
            user_prompt=f"{context}\n\n{_render_advocate_memory(adv_memory)}\n\n<question>\n{hm.question}\n</question>",
            response_schema=AdvocateAnswer,
            max_tokens=4096,
            temperature=0.3,
        )

        search_attempts = 0
        prev_query = None
        while adv.needs_research and search_attempts < _MAX_SEARCH_ATTEMPTS_PER_QUESTION:
            search_attempts += 1
            logger.info("  [round %d] Advocate searches (attempt %d): %s", round_num, search_attempts, adv.search_query)
            results = tavily_search(adv.search_query)
            transcript_lines.append(f"[searched: \"{adv.search_query}\"]")
            transcript_lines.append(f"Search found: {results[:500]}")

            retry_note = (
                f"\n\n<note>\nYour previous search for this question was: \"{prev_query}\". "
                "If you search again, use a genuinely different angle or more specific terms — "
                "repeating the same query wastes the attempt.\n</note>"
                if prev_query
                else ""
            )
            prev_query = adv.search_query

            adv = llm.complete_structured(
                system_prompt=_ADVOCATE_PROMPT,
                user_prompt=(
                    f"{context}\n\n{_render_advocate_memory(adv_memory)}\n\n"
                    f"<question>\n{hm.question}\n</question>\n\n<search_results>\n{results}\n</search_results>{retry_note}"
                ),
                response_schema=AdvocateAnswer,
                max_tokens=4096,
                temperature=0.3,
            )

        _apply_advocate_closures(adv_memory, adv)
        logger.info("  [round %d] Advocate: %s", round_num, adv.answer[:150])
        transcript_lines.append(f"Candidate Advocate: {adv.answer}")
        last_turn = (hm.question, adv.answer)
    else:
        if uncovered():
            logger.warning("  Workstream '%s' ran out of round budget with uncovered=%s", workstream.label, uncovered())
            transcript_lines.append(f"[Ran out of round budget before covering bullets {uncovered()}]")

    if skipped:
        transcript_lines.append(
            "[Deliberately skipped: " + "; ".join(f"bullet {b} ({reason})" for b, reason in sorted(skipped.items())) + "]"
        )

    transcript = "\n\n".join(transcript_lines)
    logger.info("  [round %d] Synthesizing story asset for '%s'", rounds_used, workstream.label)
    story_asset = synthesize_story_asset(llm, employer, title, workstream, transcript, hm_memory, candidate_context)
    return transcript, rounds_used, story_asset


def investigate_experience(
    llm: LLMClient,
    employer: str,
    title: str,
    start_date: str,
    end_date: str,
    bullets: list[str],
    candidate_context: str,
) -> tuple[str, list[dict]]:
    orientation = orient_experience(llm, employer, title, start_date, end_date, bullets, candidate_context)
    logger.info(
        "  Orientation: %d workstream(s): %s",
        len(orientation.workstreams),
        [w.label for w in orientation.workstreams],
    )

    # Each workstream gets its own fixed budget rather than sharing one
    # experience-wide pool — a shared pool made investigation depth
    # order-dependent (whichever workstream Orientation happened to list
    # first could legitimately need 8-9 rounds to reach a clean dimension-based
    # close, silently starving whatever came after it). _MAX_ROUNDS_PER_EXPERIENCE
    # is kept only as a coarse ceiling against pathological over-splitting.
    rounds_used_total = 0
    sections = []
    story_assets: list[dict] = []
    for ws in orientation.workstreams:
        if rounds_used_total >= _MAX_ROUNDS_PER_EXPERIENCE:
            sections.append(f"=== {ws.label} ===\n{ws.situation_and_task}\n\n[No round budget remaining — not investigated]")
            continue
        logger.info("  --- Workstream: %s ---", ws.label)
        ws_transcript, rounds_used, story_asset = investigate_workstream(
            llm, employer, title, start_date, end_date, bullets, ws, orientation.workstreams,
            candidate_context, _MAX_ROUNDS_PER_WORKSTREAM,
        )
        rounds_used_total += rounds_used
        sections.append(f"=== {ws.label} ===\n{ws.situation_and_task}\n\n{ws_transcript}")
        story_assets.append({
            "workstream": ws.label,
            "situation_and_task": ws.situation_and_task,
            **story_asset.model_dump(),
        })

    return "\n\n".join(sections), story_assets


def main() -> None:
    input_json_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/prototype_input.json"
    with open(input_json_path) as f:
        payload = json.load(f)
    structured_resume = payload["payload"]["structured_resume"]

    llm = LLMClient(model=_MODEL)
    logger.info("Using model=%s", _MODEL)

    timeline = build_chronological_timeline(structured_resume)
    concurrent_edu_notes = annotate_concurrent_education(timeline)
    concurrent_exp_notes = annotate_concurrent_experiences(timeline)

    logger.info("Chronological timeline (oldest first):")
    for e in timeline:
        logger.info("  [%s] end=%s  %s", e.kind, e.end.isoformat(), e.label)

    reflection_lines: list[str] = []
    trajectory: list[dict] = []
    transcripts = []

    for entry in timeline:
        if entry.kind == "education":
            edu = entry.raw
            coursework = ", ".join(edu.get("coursework", []) or []) or "no listed coursework"
            line = (
                f"As of {entry.end.strftime('%b %Y')}, completed {edu.get('degree', '')} "
                f"at {edu.get('institution', '')}. Coursework: {coursework}."
            )
            reflection_lines.append(line)
            trajectory.append({
                "ref": entry.ref, "kind": "education", "label": entry.label,
                "as_of": entry.end.strftime("%b %Y"), "note": line,
            })
            continue

        exp = entry.raw
        candidate_context = (
            "What's established about this candidate so far, in chronological order:\n"
            + "\n".join(reflection_lines)
            if reflection_lines
            else "This is the earliest entry on this candidate's timeline — nothing prior is established."
        )
        edu_note = concurrent_edu_notes.get(entry.ref)
        if edu_note:
            candidate_context += f"\n\nNote: {edu_note}"
        exp_note = concurrent_exp_notes.get(entry.ref)
        if exp_note:
            candidate_context += f"\n\nNote: {exp_note}"

        logger.info("\n===== %s: %s =====", entry.ref, entry.label)
        transcript, story_assets = investigate_experience(
            llm,
            exp.get("employer", ""),
            exp.get("title", ""),
            exp.get("start_date", ""),
            exp.get("end_date", ""),
            exp.get("bullets", []),
            candidate_context,
        )
        transcripts.append({
            "experience_ref": entry.ref, "employer": exp.get("employer"), "title": exp.get("title"),
            "transcript": transcript, "story_assets": story_assets,
        })

        capability_digest = "\n".join(
            f"- [{cs['epistemic_basis']}] {cs['capability']}: {cs['evidence']}"
            for sa in story_assets for cs in sa.get("capability_signals", [])
        ) or "(no capability signals extracted)"

        reflection = llm.complete_structured(
            system_prompt=_REFLECTION_PROMPT,
            user_prompt=(
                f"<candidate_context_so_far>\n{candidate_context}\n</candidate_context_so_far>\n\n"
                f"<capability_signals_from_this_experience>\n{capability_digest}\n</capability_signals_from_this_experience>"
            ),
            response_schema=ExperienceReflection,
            max_tokens=512,
            temperature=0.3,
        )
        when = "now" if entry.is_ongoing else entry.end.strftime("%b %Y")
        reflection_lines.append(f"As of {when} ({entry.label}): {reflection.reflection}")
        trajectory.append({
            "ref": entry.ref, "kind": "experience", "label": entry.label,
            "as_of": when, "reflection": reflection.reflection,
        })
        logger.info("  [reflection] %s", reflection.reflection[:200])

    out_path = "/tmp/prototype_transcripts.json"
    with open(out_path, "w") as f:
        json.dump({"experiences": transcripts, "trajectory": trajectory}, f, indent=2)
    logger.info("\nWrote %s", out_path)


if __name__ == "__main__":
    main()
