"""
Unit tests for IntentTranslator (v2).

These tests cover:
  - IntentTranslationLLMOutput schema (only LLM-owned fields)
  - _build_user_prompt() → XML data blocks, no leakage of platform fields
  - _profile_role_for_mode() / _expansion_scope_for_mode() deterministic logic
  - translate() merge logic (LLM output + platform fields → DiscoveryIntent)
  - _guardrail_check() — exclusion source enforcement, hard_constraints defence-in-depth
  - _check_ambiguity() — blocking vs non-blocking

All LLM calls are mocked. No real API calls.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from packages.contracts.agents.discovery_intent import (
    CapabilitySignal,
    DiscoveryIntent,
    ProfileSnapshot,
    RoleFamily,
)
from packages.contracts.api.discovery import (
    DiscoveryHardConstraints,
    JobDiscoveryFrontendInput,
)
from packages.infrastructure.llm.intent_translator import (
    INTENT_TRANSLATOR_SYSTEM_PROMPT_V2,
    TRANSLATOR_VERSION,
    IntentTranslationError,
    IntentTranslationLLMOutput,
    IntentTranslator,
    _expansion_scope_for_mode,
    _merge_soft_preferences,
    _profile_role_for_mode,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_frontend(
    raw_user_request: str = "Find market risk analytics roles in NYC",
    search_mode: str = "direct",
    location: str | None = "NYC",
    seniority: list[str] | None = None,
    soft_preferences: list[str] | None = None,
) -> JobDiscoveryFrontendInput:
    return JobDiscoveryFrontendInput(
        raw_user_request=raw_user_request,
        search_mode=search_mode,
        hard_constraints=DiscoveryHardConstraints(
            location=location,
            seniority=seniority or [],
        ),
        soft_preferences=soft_preferences or [],
    )


def make_profile(
    summary: str = "Risk analytics professional",
    skills: list[str] | None = None,
    subject_areas: list[str] | None = None,
) -> ProfileSnapshot:
    return ProfileSnapshot(
        summary=summary,
        technical_skills=skills or ["Python", "VaR"],
        subject_areas=subject_areas or ["market risk"],
        years_of_experience=4,
    )


_DEFAULT_TARGET_ROLE = {
    "name": "market risk analytics",
    "source": "user_explicit",
    "confidence": "high",
    "rationale": "User mentioned market risk analytics directly",
}

_UNSET = object()  # sentinel for "caller did not pass this arg"


def make_llm_output(
    interpreted_goal: str = "Find market risk analytics roles in NYC.",
    target_roles: list[dict] | None = _UNSET,  # type: ignore[assignment]
    excluded_roles: list[dict] | None = None,
    soft_prefs: list[str] | None = None,
    capability_signals: list[dict] | None = None,
    ambiguity_flags: list[str] | None = None,
) -> IntentTranslationLLMOutput:
    # Use sentinel so callers can explicitly pass [] for empty list
    if target_roles is _UNSET:
        target_roles = [_DEFAULT_TARGET_ROLE]
    return IntentTranslationLLMOutput(
        interpreted_goal=interpreted_goal,
        target_role_families=[RoleFamily(**r) for r in (target_roles or [])],
        excluded_role_families=[RoleFamily(**r) for r in (excluded_roles or [])],
        soft_preferences=soft_prefs or [],
        capability_signals=[CapabilitySignal(**c) for c in (capability_signals or [])],
        ambiguity_flags=ambiguity_flags or [],
    )


# ---------------------------------------------------------------------------
# IntentTranslationLLMOutput schema
# ---------------------------------------------------------------------------


class TestIntentTranslationLLMOutputSchema:
    def test_only_llm_owned_fields_are_present(self):
        fields = set(IntentTranslationLLMOutput.model_fields.keys())
        expected = {
            "interpreted_goal",
            "target_role_families",
            "excluded_role_families",
            "soft_preferences",
            "capability_signals",
            "ambiguity_flags",
        }
        assert fields == expected

    def test_platform_fields_not_in_llm_output(self):
        """Platform fields must NOT appear in the LLM output schema."""
        platform_fields = {
            "translator_version",
            "raw_user_request",
            "search_mode",
            "hard_constraints",
            "expansion_scope",
            "profile_role",
        }
        llm_fields = set(IntentTranslationLLMOutput.model_fields.keys())
        assert not platform_fields & llm_fields

    def test_can_construct_minimal_output(self):
        out = IntentTranslationLLMOutput(
            interpreted_goal="Find risk roles.",
            target_role_families=[],
            excluded_role_families=[],
            soft_preferences=[],
            capability_signals=[],
            ambiguity_flags=[],
        )
        assert out.interpreted_goal == "Find risk roles."

    def test_can_construct_with_role_families(self):
        out = make_llm_output()
        assert len(out.target_role_families) == 1
        assert out.target_role_families[0].source == "user_explicit"


# ---------------------------------------------------------------------------
# Deterministic derivation functions
# ---------------------------------------------------------------------------


class TestExpansionScope:
    def test_direct_is_narrow(self):
        assert _expansion_scope_for_mode("direct") == "narrow"

    def test_exploratory_is_standard(self):
        assert _expansion_scope_for_mode("exploratory") == "standard"

    def test_profile_guided_is_standard(self):
        assert _expansion_scope_for_mode("profile_guided") == "standard"

    def test_unknown_defaults_to_standard(self):
        assert _expansion_scope_for_mode("unknown_mode") == "standard"


class TestProfileRole:
    def test_direct_empty_profile_is_none(self):
        assert _profile_role_for_mode("direct", ProfileSnapshot.empty()) == "none"

    def test_direct_with_profile_is_supporting(self):
        assert _profile_role_for_mode("direct", make_profile()) == "supporting"

    def test_exploratory_empty_profile_is_none(self):
        assert _profile_role_for_mode("exploratory", ProfileSnapshot.empty()) == "none"

    def test_exploratory_with_profile_is_supporting(self):
        assert _profile_role_for_mode("exploratory", make_profile()) == "supporting"

    def test_profile_guided_is_always_primary(self):
        assert _profile_role_for_mode("profile_guided", ProfileSnapshot.empty()) == "primary"
        assert _profile_role_for_mode("profile_guided", make_profile()) == "primary"


# ---------------------------------------------------------------------------
# _build_user_prompt: XML data blocks
# ---------------------------------------------------------------------------


class TestBuildUserPrompt:
    def setup_method(self):
        self.translator = IntentTranslator()

    def test_contains_all_xml_blocks(self):
        frontend = make_frontend()
        prompt = self.translator._build_user_prompt(
            frontend, ProfileSnapshot.empty(), "none"
        )
        for tag in ["<task>", "<frontend_input_json>", "<profile_snapshot_json>", "<platform_derived_fields>"]:
            assert tag in prompt, f"Missing tag: {tag}"

    def test_frontend_data_is_json_encoded(self):
        frontend = make_frontend(raw_user_request="Find IPV roles")
        prompt = self.translator._build_user_prompt(
            frontend, ProfileSnapshot.empty(), "none"
        )
        # Extract the JSON between the frontend_input_json tags
        start = prompt.index("<frontend_input_json>") + len("<frontend_input_json>")
        end = prompt.index("</frontend_input_json>")
        data = json.loads(prompt[start:end].strip())
        assert data["raw_user_request"] == "Find IPV roles"
        assert data["search_mode"] == "direct"

    def test_empty_profile_uses_empty_json_object(self):
        frontend = make_frontend()
        prompt = self.translator._build_user_prompt(
            frontend, ProfileSnapshot.empty(), "none"
        )
        start = prompt.index("<profile_snapshot_json>") + len("<profile_snapshot_json>")
        end = prompt.index("</profile_snapshot_json>")
        profile_content = prompt[start:end].strip()
        assert profile_content == "{}"

    def test_empty_profile_includes_note(self):
        frontend = make_frontend()
        prompt = self.translator._build_user_prompt(
            frontend, ProfileSnapshot.empty(), "none"
        )
        assert "<profile_note>" in prompt
        assert "capability_signals must be empty" in prompt

    def test_non_empty_profile_is_json_encoded(self):
        frontend = make_frontend()
        profile = make_profile(summary="Risk analyst with 4 years experience")
        prompt = self.translator._build_user_prompt(frontend, profile, "supporting")
        start = prompt.index("<profile_snapshot_json>") + len("<profile_snapshot_json>")
        end = prompt.index("</profile_snapshot_json>")
        data = json.loads(prompt[start:end].strip())
        assert data["summary"] == "Risk analyst with 4 years experience"
        assert "subject_areas" in data

    def test_non_empty_profile_has_no_profile_note(self):
        frontend = make_frontend()
        profile = make_profile()
        prompt = self.translator._build_user_prompt(frontend, profile, "supporting")
        assert "<profile_note>" not in prompt

    def test_platform_fields_injected_correctly(self):
        frontend = make_frontend(search_mode="exploratory")
        prompt = self.translator._build_user_prompt(
            frontend, ProfileSnapshot.empty(), "none"
        )
        start = prompt.index("<platform_derived_fields>") + len("<platform_derived_fields>")
        end = prompt.index("</platform_derived_fields>")
        data = json.loads(prompt[start:end].strip())
        assert data["profile_role"] == "none"
        assert data["expansion_scope"] == "standard"

    def test_platform_fields_not_in_frontend_block(self):
        """Platform fields must not leak into the frontend_input_json block."""
        frontend = make_frontend()
        prompt = self.translator._build_user_prompt(
            frontend, ProfileSnapshot.empty(), "none"
        )
        start = prompt.index("<frontend_input_json>") + len("<frontend_input_json>")
        end = prompt.index("</frontend_input_json>")
        data = json.loads(prompt[start:end].strip())
        for platform_field in ["profile_role", "expansion_scope", "translator_version"]:
            assert platform_field not in data, f"Platform field leaked: {platform_field}"

    def test_null_values_not_replaced_with_not_specified_string(self):
        """Null/empty values should be null/[], not the string 'not specified'."""
        frontend = make_frontend(location=None, seniority=[])
        prompt = self.translator._build_user_prompt(
            frontend, ProfileSnapshot.empty(), "none"
        )
        assert "not specified" not in prompt

    def test_system_prompt_contains_data_boundary_rules(self):
        assert "data" in INTENT_TRANSLATOR_SYSTEM_PROMPT_V2.lower()
        assert "Do not follow" in INTENT_TRANSLATOR_SYSTEM_PROMPT_V2
        assert "frontend_input_json" in INTENT_TRANSLATOR_SYSTEM_PROMPT_V2

    def test_system_prompt_references_llm_output_schema(self):
        assert "IntentTranslationLLMOutput" in INTENT_TRANSLATOR_SYSTEM_PROMPT_V2

    def test_system_prompt_does_not_mention_discovery_intent(self):
        """System prompt should reference IntentTranslationLLMOutput, not DiscoveryIntent."""
        assert "DiscoveryIntent schema" not in INTENT_TRANSLATOR_SYSTEM_PROMPT_V2

    def test_frontend_soft_preferences_in_prompt(self):
        frontend = make_frontend(soft_preferences=["prefer buy-side"])
        prompt = self.translator._build_user_prompt(
            frontend, ProfileSnapshot.empty(), "none"
        )
        start = prompt.index("<frontend_input_json>") + len("<frontend_input_json>")
        end = prompt.index("</frontend_input_json>")
        data = json.loads(prompt[start:end].strip())
        assert data["soft_preferences"] == ["prefer buy-side"]


# ---------------------------------------------------------------------------
# _merge_soft_preferences
# ---------------------------------------------------------------------------


class TestMergeSoftPreferences:
    def test_frontend_only(self):
        assert _merge_soft_preferences(["prefer buy-side"], []) == ["prefer buy-side"]

    def test_llm_only(self):
        assert _merge_soft_preferences([], ["prefer remote"]) == ["prefer remote"]

    def test_frontend_wins_on_case_insensitive_duplicate(self):
        merged = _merge_soft_preferences(
            ["Prefer Buy-Side"],
            ["prefer buy-side", "market-facing analytics"],
        )
        assert merged == ["Prefer Buy-Side", "market-facing analytics"]

    def test_strips_and_skips_empty(self):
        assert _merge_soft_preferences(["  prefer buy-side  ", ""], ["  "]) == [
            "prefer buy-side"
        ]


# ---------------------------------------------------------------------------
# translate() — merge logic (LLM mocked)
# ---------------------------------------------------------------------------


class TestTranslateMerge:
    def _make_translator_with_mock(self, llm_output: IntentTranslationLLMOutput) -> IntentTranslator:
        mock_client = MagicMock()
        mock_client.complete_structured.return_value = llm_output
        return IntentTranslator(llm_client=mock_client)

    def test_returns_discovery_intent(self):
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(make_frontend())
        assert isinstance(intent, DiscoveryIntent)

    def test_translator_version_is_set_by_platform(self):
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(make_frontend())
        assert intent.translator_version == TRANSLATOR_VERSION

    def test_raw_user_request_is_preserved_verbatim(self):
        frontend = make_frontend(raw_user_request="Find IPV roles in NYC")
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(frontend)
        assert intent.raw_user_request == "Find IPV roles in NYC"

    def test_search_mode_is_set_from_frontend(self):
        frontend = make_frontend(search_mode="exploratory")
        llm_output = make_llm_output()
        translator = self._make_translator_with_mock(llm_output)
        intent = translator.translate(frontend)
        assert intent.search_mode == "exploratory"

    def test_expansion_scope_is_deterministic_not_llm(self):
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(make_frontend(search_mode="direct"))
        assert intent.expansion_scope == "narrow"

    def test_profile_role_is_deterministic_not_llm(self):
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(make_frontend(), profile_snapshot=None)
        assert intent.profile_role == "none"

    def test_hard_constraints_always_from_frontend(self):
        frontend = make_frontend(location="NYC", seniority=["associate"])
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(frontend)
        assert intent.hard_constraints.location == "NYC"
        assert intent.hard_constraints.seniority == ["associate"]

    def test_frontend_soft_preferences_merged_when_llm_empty(self):
        frontend = make_frontend(soft_preferences=["prefer buy-side"])
        translator = self._make_translator_with_mock(make_llm_output(soft_prefs=[]))
        intent = translator.translate(frontend)
        assert intent.soft_preferences == ["prefer buy-side"]

    def test_frontend_and_llm_soft_preferences_merged_with_dedupe(self):
        frontend = make_frontend(soft_preferences=["Prefer Buy-Side"])
        llm_output = make_llm_output(
            soft_prefs=["prefer buy-side", "market-facing analytics"]
        )
        translator = self._make_translator_with_mock(llm_output)
        intent = translator.translate(frontend)
        assert intent.soft_preferences == ["Prefer Buy-Side", "market-facing analytics"]

    def test_complete_structured_called_with_correct_schema(self):
        mock_client = MagicMock()
        mock_client.complete_structured.return_value = make_llm_output()
        translator = IntentTranslator(llm_client=mock_client)
        translator.translate(make_frontend())
        call_kwargs = mock_client.complete_structured.call_args
        assert call_kwargs.kwargs["response_schema"] is IntentTranslationLLMOutput

    def test_complete_structured_called_with_low_temperature(self):
        mock_client = MagicMock()
        mock_client.complete_structured.return_value = make_llm_output()
        translator = IntentTranslator(llm_client=mock_client)
        translator.translate(make_frontend())
        call_kwargs = mock_client.complete_structured.call_args
        assert call_kwargs.kwargs["temperature"] == 0.1

    def test_llm_target_roles_appear_in_intent(self):
        llm_output = make_llm_output(
            target_roles=[
                {
                    "name": "valuation control",
                    "source": "user_explicit",
                    "confidence": "high",
                    "rationale": "User mentioned IPV",
                }
            ]
        )
        translator = self._make_translator_with_mock(llm_output)
        intent = translator.translate(make_frontend())
        assert len(intent.target_role_families) == 1
        assert intent.target_role_families[0].name == "valuation control"

    def test_llm_failure_raises_intent_translation_error(self):
        from packages.infrastructure.llm.client import LLMCallError

        mock_client = MagicMock()
        mock_client.complete_structured.side_effect = LLMCallError("API timeout")
        translator = IntentTranslator(llm_client=mock_client)
        with pytest.raises(IntentTranslationError) as exc_info:
            translator.translate(make_frontend())
        assert exc_info.value.kind == "llm_failure"


# ---------------------------------------------------------------------------
# _guardrail_check
# ---------------------------------------------------------------------------


class TestGuardrailCheck:
    def _make_translator_with_mock(self, llm_output: IntentTranslationLLMOutput) -> IntentTranslator:
        mock_client = MagicMock()
        mock_client.complete_structured.return_value = llm_output
        return IntentTranslator(llm_client=mock_client)

    def test_exclusion_with_profile_signal_source_raises(self):
        llm_output = make_llm_output(
            excluded_roles=[
                {
                    "name": "model validation",
                    "source": "profile_signal",  # WRONG: must be user_explicit
                    "confidence": "medium",
                    "rationale": "Profile suggests avoid model val",
                }
            ]
        )
        translator = self._make_translator_with_mock(llm_output)
        with pytest.raises(IntentTranslationError) as exc_info:
            translator.translate(make_frontend())
        assert exc_info.value.kind == "guardrail_violation"
        assert "user_explicit" in str(exc_info.value)

    def test_exclusion_with_inferred_adjacent_source_raises(self):
        llm_output = make_llm_output(
            excluded_roles=[
                {
                    "name": "model validation",
                    "source": "inferred_adjacent",  # WRONG
                    "confidence": "low",
                    "rationale": "Adjacent exclusion",
                }
            ]
        )
        translator = self._make_translator_with_mock(llm_output)
        with pytest.raises(IntentTranslationError) as exc_info:
            translator.translate(make_frontend())
        assert exc_info.value.kind == "guardrail_violation"

    def test_exclusion_with_user_explicit_source_passes(self):
        llm_output = make_llm_output(
            excluded_roles=[
                {
                    "name": "model validation",
                    "source": "user_explicit",  # correct
                    "confidence": "high",
                    "rationale": "User said no model validation",
                }
            ]
        )
        translator = self._make_translator_with_mock(llm_output)
        intent = translator.translate(make_frontend())
        assert len(intent.excluded_role_families) == 1

    def test_hard_constraints_match_frontend_passes(self):
        frontend = make_frontend(location="NYC")
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(frontend)
        assert intent.hard_constraints.location == "NYC"


# ---------------------------------------------------------------------------
# _check_ambiguity
# ---------------------------------------------------------------------------


class TestCheckAmbiguity:
    def _make_translator_with_mock(self, llm_output: IntentTranslationLLMOutput) -> IntentTranslator:
        mock_client = MagicMock()
        mock_client.complete_structured.return_value = llm_output
        return IntentTranslator(llm_client=mock_client)

    def test_empty_target_roles_raises_blocking_ambiguity(self):
        llm_output = make_llm_output(
            target_roles=[],
            ambiguity_flags=["Unclear if user wants credit or market risk"],
        )
        translator = self._make_translator_with_mock(llm_output)
        with pytest.raises(IntentTranslationError) as exc_info:
            translator.translate(make_frontend())
        assert exc_info.value.kind == "blocking_ambiguity"

    def test_non_empty_targets_with_flags_does_not_raise(self):
        llm_output = make_llm_output(
            ambiguity_flags=["'risk analytics' could be credit or market risk"],
        )
        translator = self._make_translator_with_mock(llm_output)
        intent = translator.translate(make_frontend())
        assert len(intent.target_role_families) == 1
        assert len(intent.ambiguity_flags) == 1

    def test_flags_preserved_in_intent(self):
        llm_output = make_llm_output(
            ambiguity_flags=["Credit vs market risk unclear"],
        )
        translator = self._make_translator_with_mock(llm_output)
        intent = translator.translate(make_frontend())
        assert "Credit vs market risk unclear" in intent.ambiguity_flags


# ---------------------------------------------------------------------------
# Profile context: profile_role propagation
# ---------------------------------------------------------------------------


class TestProfileContext:
    def _make_translator_with_mock(self, llm_output: IntentTranslationLLMOutput) -> IntentTranslator:
        mock_client = MagicMock()
        mock_client.complete_structured.return_value = llm_output
        return IntentTranslator(llm_client=mock_client)

    def test_profile_role_none_when_no_profile_direct(self):
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(make_frontend(search_mode="direct"))
        assert intent.profile_role == "none"

    def test_profile_role_supporting_when_profile_provided_exploratory(self):
        profile = make_profile()
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(
            make_frontend(search_mode="exploratory"), profile_snapshot=profile
        )
        assert intent.profile_role == "supporting"

    def test_profile_role_primary_for_profile_guided(self):
        profile = make_profile()
        translator = self._make_translator_with_mock(make_llm_output())
        intent = translator.translate(
            make_frontend(search_mode="profile_guided"), profile_snapshot=profile
        )
        assert intent.profile_role == "primary"

    def test_capability_signals_in_profile_guided_are_preserved(self):
        llm_output = make_llm_output(
            capability_signals=[
                {
                    "cluster_name": "VaR modeling",
                    "description": "Quantitative risk modeling",
                    "adjacent_role_targets": ["market risk analytics"],
                    "signal_type": "domain",
                }
            ]
        )
        mock_client = MagicMock()
        mock_client.complete_structured.return_value = llm_output
        translator = IntentTranslator(llm_client=mock_client)
        intent = translator.translate(
            make_frontend(search_mode="profile_guided"), profile_snapshot=make_profile()
        )
        assert len(intent.capability_signals) == 1
        assert intent.capability_signals[0].cluster_name == "VaR modeling"
