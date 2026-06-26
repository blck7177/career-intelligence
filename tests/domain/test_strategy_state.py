"""Tests for strategy state reducer (validate, apply, materialize)."""

from __future__ import annotations

import pytest

from packages.contracts.strategy.state import SearchStrategyState, StrategyPatchError
from packages.domain.strategy_state import (
    apply_strategy_patch,
    is_board_source,
    materialize_discovery_hints,
    validate_strategy_patch,
)


class TestValidateStrategyPatch:
    def test_empty_patch_is_valid(self):
        patch = validate_strategy_patch({})
        assert patch.effective_sources == []

    def test_rejects_unknown_fields(self):
        with pytest.raises(StrategyPatchError, match="schema validation failed"):
            validate_strategy_patch({"source_weights": ["x"]})

    def test_accepts_valid_role_category_id(self):
        patch = validate_strategy_patch(
            {"coverage_by_role_category": {"market_risk_exposure": "weak"}}
        )
        assert patch.coverage_by_role_category["market_risk_exposure"] == "weak"

    def test_rejects_invalid_role_category_key(self):
        with pytest.raises(StrategyPatchError, match="not a valid role category"):
            validate_strategy_patch(
                {"coverage_by_role_category": {"Market Risk": "missing"}}
            )


class TestApplyStrategyPatch:
    def test_list_fields_union_dedup(self):
        base = SearchStrategyState.empty("ws_1")
        base.effective_sources = ["greenhouse.io/acme"]
        patch = validate_strategy_patch(
            {
                "effective_sources": ["greenhouse.io/acme", "lever.co/xyz"],
                "avoid_sources": ["bad.com — bot-blocked"],
            }
        )
        result = apply_strategy_patch(
            base,
            patch,
            workspace_id="ws_1",
            reflection_run_id="run_r",
            reflection_task_id="task_r",
        )
        assert result.effective_sources == ["greenhouse.io/acme", "lever.co/xyz"]
        assert result.avoid_sources == ["bad.com — bot-blocked"]

    def test_recommended_next_searches_replaces(self):
        base = SearchStrategyState.empty("ws_1")
        base.recommended_next_searches = ["old direction"]
        patch = validate_strategy_patch({"recommended_next_searches": ["new direction"]})
        result = apply_strategy_patch(
            base,
            patch,
            workspace_id="ws_1",
            reflection_run_id="run_r",
            reflection_task_id="task_r",
        )
        assert result.recommended_next_searches == ["new direction"]

    def test_empty_recommended_does_not_clear_existing(self):
        base = SearchStrategyState.empty("ws_1")
        base.recommended_next_searches = ["keep me"]
        patch = validate_strategy_patch({})
        result = apply_strategy_patch(
            base,
            patch,
            workspace_id="ws_1",
            reflection_run_id="run_r",
            reflection_task_id="task_r",
        )
        assert result.recommended_next_searches == ["keep me"]

    def test_coverage_merged_per_key(self):
        base = SearchStrategyState.empty("ws_1")
        base.coverage_by_role_category = {"market_risk_exposure": "sufficient"}
        patch = validate_strategy_patch(
            {"coverage_by_role_category": {"valuation_control_ipv": "missing"}}
        )
        result = apply_strategy_patch(
            base,
            patch,
            workspace_id="ws_1",
            reflection_run_id="run_r",
            reflection_task_id="task_r",
        )
        assert result.coverage_by_role_category == {
            "market_risk_exposure": "sufficient",
            "valuation_control_ipv": "missing",
        }


class TestMaterializeDiscoveryHints:
    def test_maps_weak_missing_to_coverage_gaps(self):
        state = SearchStrategyState.empty("ws_1")
        state.effective_sources = [
            "https://boards.greenhouse.io/acme",
            "linkedin.com/jobs",
        ]
        state.avoid_sources = ["blocked.com — 403"]
        state.effective_query_patterns = ["site:greenhouse.io risk analyst"]
        state.avoid_query_patterns = ["risk analyst jobs"]
        state.coverage_by_role_category = {
            "market_risk_exposure": "weak",
            "valuation_control_ipv": "missing",
        }
        state.key_learnings = ["JPM board filter too narrow"]
        state.recommended_next_searches = ["Retry valuation control with broader titles"]

        src, diag = materialize_discovery_hints(state)

        assert "https://boards.greenhouse.io/acme" in src.known_boards
        assert "linkedin.com/jobs" not in src.known_boards
        assert src.avoid_sources == ["blocked.com — 403"]
        assert any("market_risk" in g.lower() or "Market Risk" in g for g in diag.coverage_gaps)
        assert diag.recommended_next_searches == ["Retry valuation control with broader titles"]
        assert any("Avoid query pattern" in l for l in diag.key_learnings)


class TestIsBoardSource:
    def test_greenhouse_is_board(self):
        assert is_board_source("https://boards.greenhouse.io/acme")

    def test_generic_domain_is_not_board(self):
        assert not is_board_source("linkedin.com")
