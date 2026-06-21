"""
Intent Translator — converts JobDiscoveryFrontendInput into DiscoveryIntent.

Lives in infrastructure/llm/ because it calls LLMClient.
Domain logic (discovery_planner.py) does not import this module.

Key design principles:
  - One LLM call per translation (temperature=0.1 — extraction, not planning)
  - Versioned system prompt: bump TRANSLATOR_VERSION on any prompt change
  - Post-LLM guardrail check is deterministic Python — no second LLM call
  - expansion_scope and profile_role are computed deterministically, not by LLM
  - Blocking ambiguity (empty target_role_families) raises IntentTranslationError
    with kind="blocking_ambiguity" — worker routes to needs_review
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import ValidationError

from packages.contracts.agents.discovery_intent import (
    DiscoveryIntent,
    ProfileSnapshot,
    RoleFamily,
)
from packages.contracts.api.discovery import (
    DiscoveryHardConstraints,
    JobDiscoveryFrontendInput,
)
from packages.infrastructure.llm.client import LLMClient, LLMCallError, get_llm_client

logger = logging.getLogger(__name__)

TRANSLATOR_VERSION = "v1.0"

# ---------------------------------------------------------------------------
# System prompt (versioned)
# ---------------------------------------------------------------------------

INTENT_TRANSLATOR_SYSTEM_PROMPT_V1 = """
You are a career search intent extraction system.

Your job is to analyze a user's job search request and extract structured
intent — NOT to plan how to search for jobs.

## Core rules

1. Only include information the user explicitly provided or that is
   semantically obvious from their words.

2. Do NOT add constraints the user did not state:
   - No location → hard_constraints.location = null
   - No seniority → hard_constraints.seniority = []
   - No visa requirement → hard_constraints.visa_note = null
   - No compensation → hard_constraints.compensation_range = null

3. Do NOT generate search strategies, source lists, query plans, or
   instructions on how to search.

4. For each role family you include in target_role_families:
   - source = "user_explicit" if the user mentioned it directly or used
     a common synonym/abbreviation (e.g. "IPV" for "independent price
     verification", "VaR" for "value at risk")
   - source = "inferred_adjacent" ONLY if the adjacency is semantically
     obvious and natural — not creative or speculative
     (e.g. user says "market risk" → "exposure management" is a reasonable
      adjacent; "data science" is NOT adjacent without more context)
   - source = "profile_signal" if it comes ONLY from the profile,
     not from the user's request text

5. For excluded_role_families: source MUST be "user_explicit".
   Never infer exclusions. Never exclude based on profile alone.

6. For soft_preferences: only include what the user stated.
   Do not add preferences that seem reasonable but were not said.

7. Ambiguity: if something is unclear, add it to ambiguity_flags.
   Do NOT resolve ambiguity by guessing or defaulting.
   Example: if user says "risk analytics" without specifying credit vs
   market risk, flag it — do not auto-pick one.

8. capability_signals: only populate when profile data is provided AND
   profile_role is "supporting" or "primary".

9. interpreted_goal: write exactly one sentence summarizing what the
   agent should find. Be specific about role type, location (if given),
   level (if given), and any hard exclusions.

10. For search_mode = "direct":
    - expansion_scope must be "narrow"
    - inferred_adjacent roles are NOT allowed unless they are direct
      synonyms or well-known abbreviations of the same role
    - Do not add adjacent role families the user did not mention

## Output

Return ONLY a valid JSON object. No markdown, no explanation.
The JSON must conform to the DiscoveryIntent schema.
""".strip()


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class IntentTranslationError(Exception):
    """
    Raised when intent translation cannot produce a valid DiscoveryIntent.

    kind:
      "blocking_ambiguity"  — target_role_families is empty; task → needs_review
      "schema_failure"      — LLM output failed DiscoveryIntent validation
      "llm_failure"         — LLM API call failed
      "guardrail_violation" — LLM added unapproved hard constraints
    """

    def __init__(
        self,
        message: str,
        kind: Literal[
            "blocking_ambiguity",
            "schema_failure",
            "llm_failure",
            "guardrail_violation",
        ] = "schema_failure",
    ) -> None:
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------------------
# IntentTranslator
# ---------------------------------------------------------------------------


class IntentTranslator:
    """
    Translates JobDiscoveryFrontendInput + optional ProfileSnapshot
    into a structured DiscoveryIntent via one LLM call.

    Usage:
        translator = IntentTranslator(llm_client=get_llm_client())
        intent = translator.translate(frontend_input, profile_snapshot)
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        version: str = TRANSLATOR_VERSION,
    ) -> None:
        self._client = llm_client or get_llm_client()
        self._version = version

    def translate(
        self,
        frontend_input: JobDiscoveryFrontendInput,
        profile_snapshot: ProfileSnapshot | None = None,
    ) -> DiscoveryIntent:
        """
        Perform intent translation.

        Returns a DiscoveryIntent with:
          - expansion_scope computed deterministically from search_mode
          - profile_role computed deterministically from search_mode + profile
          - guardrail check applied after LLM output

        Raises IntentTranslationError on any failure.
        """
        if profile_snapshot is None:
            profile_snapshot = ProfileSnapshot.empty()

        user_prompt = self._build_user_prompt(frontend_input, profile_snapshot)

        logger.info(
            "intent_translator: translating for search_mode=%s raw_request=%r",
            frontend_input.search_mode,
            frontend_input.raw_user_request[:80],
        )

        try:
            raw = self._client.complete_simple(
                system_prompt=INTENT_TRANSLATOR_SYSTEM_PROMPT_V1,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=2000,
            )
        except LLMCallError as exc:
            raise IntentTranslationError(
                f"LLM call failed during intent translation: {exc}",
                kind="llm_failure",
            ) from exc

        # Strip markdown fences if LLM wrapped output despite instructions
        cleaned = _strip_json_fences(raw)

        try:
            raw_dict = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise IntentTranslationError(
                f"LLM output is not valid JSON: {exc}\nRaw output: {cleaned[:300]}",
                kind="schema_failure",
            ) from exc

        # Overwrite fields that must be computed deterministically
        raw_dict["translator_version"] = self._version
        raw_dict["raw_user_request"] = frontend_input.raw_user_request
        raw_dict["search_mode"] = frontend_input.search_mode
        raw_dict["expansion_scope"] = _expansion_scope_for_mode(
            frontend_input.search_mode
        )
        raw_dict["profile_role"] = _profile_role_for_mode(
            frontend_input.search_mode, profile_snapshot
        )
        # hard_constraints: always use the original frontend input, never LLM
        raw_dict["hard_constraints"] = frontend_input.hard_constraints.model_dump()

        try:
            intent = DiscoveryIntent.model_validate(raw_dict)
        except ValidationError as exc:
            raise IntentTranslationError(
                f"LLM output failed DiscoveryIntent schema validation: {exc}",
                kind="schema_failure",
            ) from exc

        self._guardrail_check(intent, frontend_input)
        self._check_ambiguity(intent)

        logger.info(
            "intent_translator: success — goal=%r lanes=%d exclusions=%d flags=%d",
            intent.interpreted_goal[:80],
            len(intent.target_role_families),
            len(intent.excluded_role_families),
            len(intent.ambiguity_flags),
        )
        return intent

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        frontend_input: JobDiscoveryFrontendInput,
        profile_snapshot: ProfileSnapshot,
    ) -> str:
        c = frontend_input.hard_constraints
        lines: list[str] = [
            "## User Input",
            "",
            f'raw_user_request: "{frontend_input.raw_user_request}"',
            f"search_mode: {frontend_input.search_mode}",
            "",
            "## Hard Constraints (from user — do NOT add any that are not listed)",
            f"  location: {c.location or 'not specified'}",
            f"  seniority: {c.seniority or 'not specified'}",
            f"  exclude_role_types: {c.exclude_role_types or 'not specified'}",
            f"  must_include_keywords: {c.must_include_keywords or 'not specified'}",
            f"  work_arrangement: {c.work_arrangement or 'not specified'}",
            f"  visa_note: {c.visa_note or 'not specified'}",
            f"  compensation_range: {c.compensation_range or 'not specified'}",
        ]

        if profile_snapshot.is_empty:
            lines += [
                "",
                "## Profile",
                "No profile provided. capability_signals must be empty. "
                "Do not infer role targets from profile.",
            ]
        else:
            lines += [
                "",
                "## Profile",
                f"(profile_role will be set to: "
                f"{_profile_role_for_mode(frontend_input.search_mode, profile_snapshot)})",
            ]
            if profile_snapshot.summary:
                lines.append(f"summary: {profile_snapshot.summary}")
            if profile_snapshot.experience_summary:
                lines.append(
                    f"experience_summary: {profile_snapshot.experience_summary}"
                )
            if profile_snapshot.technical_skills:
                lines.append(
                    f"technical_skills: {', '.join(profile_snapshot.technical_skills)}"
                )
            if profile_snapshot.domain_areas:
                lines.append(
                    f"domain_areas: {', '.join(profile_snapshot.domain_areas)}"
                )
            if profile_snapshot.years_of_experience is not None:
                lines.append(
                    f"years_of_experience: {profile_snapshot.years_of_experience}"
                )

        lines += [
            "",
            "## Instructions",
            "Return ONLY a JSON object with these top-level keys:",
            "  interpreted_goal, target_role_families, excluded_role_families,",
            "  soft_preferences, capability_signals, ambiguity_flags",
            "",
            "Do NOT include: translator_version, raw_user_request, search_mode,",
            "  hard_constraints, expansion_scope, profile_role",
            "(These are set by the platform, not by you.)",
        ]

        return "\n".join(lines)

    def _guardrail_check(
        self,
        intent: DiscoveryIntent,
        frontend_input: JobDiscoveryFrontendInput,
    ) -> None:
        """
        Deterministic post-LLM safety check.

        Verifies the LLM did not silently add hard constraints the user
        never specified. Raises IntentTranslationError on violation.

        Note: hard_constraints are overwritten from frontend_input before
        model validation, so this check is a safety net for future changes.
        """
        original = frontend_input.hard_constraints
        translated = intent.hard_constraints

        if translated.location and not original.location:
            raise IntentTranslationError(
                "Guardrail: LLM added location constraint not present in user input. "
                f"Got: {translated.location!r}",
                kind="guardrail_violation",
            )

        if translated.seniority and not original.seniority:
            raise IntentTranslationError(
                "Guardrail: LLM added seniority constraint not present in user input. "
                f"Got: {translated.seniority!r}",
                kind="guardrail_violation",
            )

        # Verify exclusions only come from user_explicit sources
        for excl in intent.excluded_role_families:
            if excl.source != "user_explicit":
                raise IntentTranslationError(
                    f"Guardrail: excluded_role_families must all have source='user_explicit'. "
                    f"Got source={excl.source!r} for {excl.name!r}",
                    kind="guardrail_violation",
                )

    def _check_ambiguity(self, intent: DiscoveryIntent) -> None:
        """
        Check ambiguity level and raise if blocking.

        Blocking ambiguity: target_role_families is empty.
        Non-blocking: ambiguity_flags present but role families exist.
        """
        if not intent.target_role_families:
            flags_summary = "; ".join(intent.ambiguity_flags[:3]) or "no flags provided"
            raise IntentTranslationError(
                f"Blocking ambiguity: no target role families identified. "
                f"Ambiguity flags: {flags_summary}",
                kind="blocking_ambiguity",
            )


# ---------------------------------------------------------------------------
# Deterministic derivations (never LLM-decided)
# ---------------------------------------------------------------------------


def _expansion_scope_for_mode(
    search_mode: str,
) -> Literal["narrow", "standard", "wide"]:
    """
    Compute expansion_scope from search_mode.
    direct         → narrow  (synonyms + title aliases only)
    exploratory    → standard
    profile_guided → standard
    """
    return {
        "direct": "narrow",
        "exploratory": "standard",
        "profile_guided": "standard",
    }.get(search_mode, "standard")  # type: ignore[return-value]


def _profile_role_for_mode(
    search_mode: str,
    profile_snapshot: ProfileSnapshot,
) -> Literal["none", "supporting", "primary"]:
    """
    Compute profile_role from search_mode and whether a profile exists.
    direct         → none (or supporting if profile is non-empty)
    exploratory    → supporting (if profile non-empty), else none
    profile_guided → primary
    """
    has_profile = not profile_snapshot.is_empty
    if search_mode == "profile_guided":
        return "primary"
    if search_mode == "exploratory":
        return "supporting" if has_profile else "none"
    # direct
    return "supporting" if has_profile else "none"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (```json or ```) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        return "\n".join(inner).strip()
    return text
