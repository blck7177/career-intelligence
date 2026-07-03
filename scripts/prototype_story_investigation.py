"""
Standalone prototype — NOT wired into the pipeline, NOT imported by any handler.

Tests the deterministic Hiring-Manager / Candidate-Advocate investigation loop
discussed in dev_note/career/phase16-candidate/ before committing to rewiring
apps/worker/tasks/story_bank_build.py and retiring the candidate-story-agent
OpenClaw registration.

Design:
  - Hiring Manager and Candidate Advocate are both plain LLMClient.complete_structured()
    calls (no OpenClaw, no agent session) — each turn only sees the transcript-so-far
    passed explicitly as a prompt argument, so the model cannot pre-plan the whole
    interview in one shot the way the OpenClaw agent did.
  - Advocate answers as a "project replication" attempt, not a defensive Q&A:
    given the question, reconstruct how this piece of work would actually be
    done, separating what's source_stated / a logical_necessity / a calibrated
    domain_replication / a genuine_fork only the candidate could resolve. If it
    wants to ground the replication in real practice, it does a real Tavily
    search (direct API, same TAVILY_API_KEY the OpenClaw gateway uses), bounded
    to 2 search attempts per question, then answers again with results.
  - Hiring Manager: after each Advocate answer, can also choose to verify a claim
    itself via a real search, independent of what the Advocate reported — this is
    the "reviewer can fact-check, not just trust the self-report" mechanism from
    the design discussion.

Run inside a container that has OPENAI_API_KEY and TAVILY_API_KEY (worker-agent
already has both):

    docker exec compose-worker-agent-1 sh -c "cd /app && python3 /tmp/prototype_story_investigation.py"

Output: prints each experience's transcript, and writes them to
/tmp/prototype_transcripts.json for inspection.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Literal

import httpx
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, "/app")
from packages.infrastructure.llm.client import LLMClient  # noqa: E402

_MODEL = os.environ.get("CANDIDATE_STORY_STRUCTURING_MODEL", "gpt-5.4-mini")
_TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
_MAX_ROUNDS_PER_EXPERIENCE = 16
_MAX_SEARCH_ATTEMPTS_PER_QUESTION = 2


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
# Schemas
# ---------------------------------------------------------------------------


class HiringManagerTurn(BaseModel):
    done: bool = Field(description="True only if every bullet is covered or explicitly skipped — see coverage rules.")
    question: str = ""
    addresses_bullets: list[int] = Field(
        default_factory=list,
        description="Bullet indices this question is about. Can be one bullet, or several if they're the same piece of work (e.g. sentence fragments split across bullets).",
    )
    skip_bullets: list[int] = Field(
        default_factory=list,
        description="Bullet indices you're deliberately choosing not to ask about, because they're genuinely trivial/self-evident. Must be paired with skip_reason.",
    )
    skip_reason: str = ""
    verify: bool = Field(
        default=False,
        description="True if you want to independently fact-check the Advocate's previous answer via search, rather than trusting it.",
    )
    verify_query: str = ""


class AdvocateAttempt(BaseModel):
    answer: str
    basis: Literal["source_stated", "logical_necessity", "domain_replication", "genuine_fork"] = Field(
        description="What kind of claim this answer actually is — see the four basis definitions in the prompt."
    )
    needs_research: bool = Field(
        default=False,
        description="True if searching would sharpen this with real domain grounding, or would help resolve a genuine_fork.",
    )
    search_query: str = ""


_BASIS_LABELS = {
    "source_stated": "source-stated",
    "logical_necessity": "logical necessity",
    "domain_replication": "domain replication",
    "genuine_fork": "genuine fork — needs candidate",
}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_HIRING_MANAGER_PROMPT = """\
You are a skeptical, technically sharp Hiring Manager interviewing a candidate \
about ONE specific experience from their resume. You do not accept bullet text \
at face value. You ask the question a demanding, competent interviewer would ask \
to find out what is really behind a claim — never a generic question ("tell me \
more", "what was the impact?"), always something specific to what this bullet \
claims. Good questions probe: what was decided vs. executed, what a superficial \
version of this claim would look like vs. real ownership, what's conspicuously \
not said that a fuller account would mention.

Note: bullets may be split mid-sentence (a PDF line-wrap artifact) — read \
adjacent bullets together to see if they're actually one claim before treating \
them as separate.

You have TWO separate jobs each turn, and they are not the same thing:

**1. Depth** — for whatever thread you're currently pursuing, keep pushing past \
the surface until further questions on THIS thread would only restate what's \
already established. This is a per-thread judgment, not a whole-interview one.

**2. Coverage** — every bullet in this experience needs to be asked about at \
least once, or explicitly skipped with a reason. You will be told each turn \
which bullet indices are still untouched (`uncovered_bullets`). Having exhausted \
your current thread (job 1) does NOT mean the interview is done if uncovered \
bullets remain — it means it's time to open a new thread on one of them.

Each turn, decide:
- Ask ONE question — either going deeper on the current thread (if it still has \
real gaps worth probing), or opening a new thread on an uncovered bullet.
- Or: explicitly skip one or more uncovered bullets via skip_bullets, with a real \
skip_reason (genuinely trivial/self-evident content only — not just "already \
covered by another bullet" unless it truly is the same claim).
- Or: set done=true — ONLY valid once every bullet is either addressed at some \
point in the transcript or explicitly skipped. If uncovered_bullets is non-empty, \
done=true will be rejected.
- After seeing the Advocate's last answer (if any), do you actually believe it, \
or is it worth independently checking via search rather than taking their word \
for it? Only set verify=true if checking would plausibly catch something wrong \
or add real information — not as a routine habit.

Budget awareness: you'll be told how many rounds you've used out of your total \
budget. As budget runs low, prioritize opening uncovered bullets (even briefly) \
over further depth on an already-rich thread — an uncovered bullet with zero \
questions is worse than a covered one with fewer follow-ups than ideal.
"""

_ADVOCATE_PROMPT = """\
You are the Candidate Advocate. A Hiring Manager just asked a pointed question \
about one piece of this candidate's work. Your job is not to defend against \
skepticism — it's to REPLICATE the piece of work being asked about, the way a \
senior practitioner in this field would if they had to reproduce it themselves \
from just the bullet text. A real replication attempt naturally separates three \
things, and your answer should too:

1. What the source material (the bullet / resume) actually states outright.

2. What a working replication REQUIRES you to fill in using domain expertise — \
standard methods, typical tooling, the usual way this kind of work gets done — \
because the source doesn't spell it out, but *some* concrete approach has to \
exist for the described result to be possible at all. This is the bulk of what \
a real replication attempt produces, and it is expected to be detailed and \
specific, not hedged into vagueness — you are not guessing wildly, you are \
applying real domain knowledge to reconstruct a plausible concrete version of \
the work. Calibrate it to the candidate's actual context (title, tenure at this \
experience, seniority signals elsewhere in the resume) — the same bullet \
implies a different level of ownership from a 4-month practicum than from a \
3-year individual-contributor role.

3. Genuine FORKS — points where more than one reasonable approach exists and \
nothing in the bullet or context tells you which one this candidate actually \
took. This is different from "I don't know" — it's "here are the 2-3 plausible \
branches, and only the candidate can tell us which one." Naming the fork \
explicitly (not just saying "can't confirm") is more useful downstream than a \
flat refusal.

Write your answer as an actual replication attempt — walk through what you'd \
need to do, in what order, with what methods — not as a defensive hedge-laden \
paragraph. Specificity is the goal; a vague answer that could apply to any \
project is a failure even if it's technically "safe."

At the end, classify what you just gave using `basis`:
- `source_stated`: this part is directly in the bullet/resume, not reconstructed.
- `logical_necessity`: this part is not stated, but the bullet is impossible to \
  be true without it — the answer should make that "not possible without" chain \
  explicit.
- `domain_replication`: this part is your calibrated reconstruction of how this \
  work is actually done, filling a gap the source leaves open. This is the \
  normal, expected outcome of a real replication attempt — use it freely, don't \
  reserve it for when you're stuck, and don't undersell it by hedging it into \
  vagueness just because it isn't source_stated.
- `genuine_fork`: multiple real approaches exist and nothing here tells you \
  which one — flag it, don't force a single answer to sound resolved.

If most of your answer is source_stated or logical_necessity, `basis` should \
reflect that. Use `domain_replication` only for the parts you actually had to \
reconstruct, and `genuine_fork` only when the question really can't be settled \
by domain knowledge — not as a safety default.

If your replication attempt hits a point where your own domain knowledge is \
uncertain about what's actually standard/typical for this kind of work (not \
about this specific candidate — about the field itself), search to ground the \
replication in real practice rather than guessing. Search is a normal part of \
doing a careful replication, not a last resort. Only skip it when you're \
already confident about the standard approach, or when the gap is specifically \
about this one candidate's personal choices, which no search could ever answer.

If you're given search results, use them to sharpen the replication. If they \
genuinely don't help, say so and continue with your own domain judgment rather \
than forcing them into the answer.
"""


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def investigate_experience(
    llm: LLMClient,
    employer: str,
    title: str,
    start_date: str,
    end_date: str,
    bullets: list[str],
    candidate_context: str,
) -> str:
    bullets_block = "\n".join(f"{i}: {b}" for i, b in enumerate(bullets))
    context = (
        f"<experience>\nEmployer: {employer}\nTitle: {title}\n"
        f"Dates: {start_date} - {end_date}\nBullets:\n{bullets_block}\n</experience>\n"
        f"<candidate_context>\n{candidate_context}\n</candidate_context>"
    )

    transcript_lines: list[str] = []
    covered: set[int] = set()
    skipped: dict[int, str] = {}
    all_indices = set(range(len(bullets)))

    def uncovered() -> list[int]:
        return sorted(all_indices - covered - skipped.keys())

    def call_hm(round_num: int, forced: bool = False) -> HiringManagerTurn:
        dialogue_so_far = "\n\n".join(transcript_lines) or "(no questions asked yet)"
        progress = (
            f"<progress>\nRounds used: {round_num}/{_MAX_ROUNDS_PER_EXPERIENCE}\n"
            f"Uncovered bullets (never asked about or skipped): {uncovered()}\n</progress>"
        )
        forced_note = (
            "\n\n<forced_note>\nYou set done=true but bullets "
            f"{uncovered()} are still uncovered. You cannot finish — either ask "
            "about one of them now, or add them to skip_bullets with a real reason.\n</forced_note>"
            if forced
            else ""
        )
        return llm.complete_structured(
            system_prompt=_HIRING_MANAGER_PROMPT,
            user_prompt=f"{context}\n\n{progress}\n\n<dialogue_so_far>\n{dialogue_so_far}\n</dialogue_so_far>{forced_note}",
            response_schema=HiringManagerTurn,
            max_tokens=1024,
            temperature=0.4,
        )

    for round_num in range(_MAX_ROUNDS_PER_EXPERIENCE):
        hm = call_hm(round_num)

        if hm.verify and transcript_lines:
            logger.info("  [round %d] Hiring Manager verifies previous answer", round_num)
            verify_results = tavily_search(hm.verify_query)
            transcript_lines.append(f"[Hiring Manager independently verified: \"{hm.verify_query}\"]")
            transcript_lines.append(f"Verification found: {verify_results[:500]}")

        for b in hm.skip_bullets:
            skipped[b] = hm.skip_reason or "(no reason given)"
        if hm.skip_bullets:
            logger.info("  [round %d] Hiring Manager skips bullets %s: %s", round_num, hm.skip_bullets, hm.skip_reason)

        if hm.done:
            if uncovered():
                logger.info("  [round %d] Hiring Manager declared done with uncovered=%s — forcing retry", round_num, uncovered())
                hm = call_hm(round_num, forced=True)
                for b in hm.skip_bullets:
                    skipped[b] = hm.skip_reason or "(no reason given)"
                if hm.done and uncovered():
                    logger.warning("  [round %d] Hiring Manager still insists done with uncovered=%s — stopping honestly", round_num, uncovered())
                    transcript_lines.append(
                        f"[Investigation ended before covering bullets {uncovered()} — Hiring Manager would not continue]"
                    )
                    break
            if hm.done:
                logger.info("  [round %d] Hiring Manager: done (coverage complete)", round_num)
                break

        covered |= set(hm.addresses_bullets)
        logger.info("  [round %d] Hiring Manager: %s", round_num, hm.question)
        transcript_lines.append(f"Hiring Manager: {hm.question}")

        dialogue_so_far = "\n\n".join(transcript_lines)
        adv = llm.complete_structured(
            system_prompt=_ADVOCATE_PROMPT,
            user_prompt=f"{context}\n\n<dialogue_so_far>\n{dialogue_so_far}\n</dialogue_so_far>\n\n<question>\n{hm.question}\n</question>",
            response_schema=AdvocateAttempt,
            max_tokens=2048,
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

            dialogue_so_far = "\n\n".join(transcript_lines)
            adv = llm.complete_structured(
                system_prompt=_ADVOCATE_PROMPT,
                user_prompt=(
                    f"{context}\n\n<dialogue_so_far>\n{dialogue_so_far}\n</dialogue_so_far>\n\n"
                    f"<question>\n{hm.question}\n</question>\n\n<search_results>\n{results}\n</search_results>{retry_note}"
                ),
                response_schema=AdvocateAttempt,
                max_tokens=2048,
                temperature=0.3,
            )

        logger.info("  [round %d] Advocate (basis=%s): %s", round_num, adv.basis, adv.answer[:150])
        transcript_lines.append(f"Candidate Advocate [{_BASIS_LABELS[adv.basis]}]: {adv.answer}")
    else:
        if uncovered():
            logger.warning("  Ran out of round budget with uncovered=%s", uncovered())
            transcript_lines.append(
                f"[Ran out of round budget before covering bullets {uncovered()}]"
            )

    if skipped:
        transcript_lines.append(
            "[Deliberately skipped: " + "; ".join(f"bullet {b} ({reason})" for b, reason in sorted(skipped.items())) + "]"
        )

    return "\n\n".join(transcript_lines)


def main() -> None:
    input_json_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/prototype_input.json"
    with open(input_json_path) as f:
        payload = json.load(f)
    structured_resume = payload["payload"]["structured_resume"]

    llm = LLMClient(model=_MODEL)
    logger.info("Using model=%s", _MODEL)

    experiences = structured_resume["experiences"]
    education = structured_resume.get("education", [])

    other_experiences_lines = [
        f"- {e.get('title')} @ {e.get('employer')} ({e.get('start_date')} - {e.get('end_date')})"
        for e in experiences
    ]
    education_lines = [
        f"- {e.get('degree')}, {e.get('institution')} ({e.get('graduation_date')})" for e in education
    ]
    candidate_context = (
        "All experiences on this resume (for calibrating seniority/tenure):\n"
        + "\n".join(other_experiences_lines)
        + "\n\nEducation:\n"
        + "\n".join(education_lines)
    )

    transcripts = []
    for i, exp in enumerate(experiences):
        logger.info("\n===== Experience exp_%d: %s @ %s =====", i, exp.get("title"), exp.get("employer"))
        transcript = investigate_experience(
            llm,
            exp.get("employer", ""),
            exp.get("title", ""),
            exp.get("start_date", ""),
            exp.get("end_date", ""),
            exp.get("bullets", []),
            candidate_context,
        )
        transcripts.append({"experience_ref": f"exp_{i}", "employer": exp.get("employer"), "title": exp.get("title"), "transcript": transcript})

    out_path = "/tmp/prototype_transcripts.json"
    with open(out_path, "w") as f:
        json.dump({"experiences": transcripts}, f, indent=2)
    logger.info("\nWrote %s", out_path)


if __name__ == "__main__":
    main()
