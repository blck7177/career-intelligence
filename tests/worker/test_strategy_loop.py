"""End-to-end strategy loop test (domain + repository, no web search)."""

from __future__ import annotations

from datetime import datetime, timezone

from packages.contracts.strategy.state import SearchStrategyState
from packages.domain.agent_jobs.discovery_planner import build_discovery_task_spec
from packages.domain.strategy_state import (
    apply_strategy_patch,
    materialize_discovery_hints,
    state_from_db_row,
    state_to_db_json,
    validate_strategy_patch,
)
from packages.contracts.agents.discovery_intent import DiscoveryIntent, RoleFamily
from packages.contracts.api.discovery import DiscoveryHardConstraints


def _minimal_discovery_intent() -> DiscoveryIntent:
    return DiscoveryIntent(
        raw_user_request="find risk roles",
        interpreted_goal="Find market risk roles in NYC",
        search_mode="exploratory",
        target_role_families=[
            RoleFamily(
                name="market risk analytics",
                rationale="user request",
                source="user_explicit",
            )
        ],
        excluded_role_families=[],
        hard_constraints=DiscoveryHardConstraints(),
        profile_role="none",
        expansion_scope="standard",
    )


class TestStrategyLoop:
    def test_patch_apply_materialize_into_discovery_task_spec(self):
        patch = validate_strategy_patch(
            {
                "effective_sources": ["https://boards.greenhouse.io/acme", "news.ycombinator.com"],
                "avoid_sources": ["blocked.com — bot-blocked"],
                "effective_query_patterns": ["site:greenhouse.io risk"],
                "coverage_by_role_category": {"market_risk_exposure": "missing"},
                "key_learnings": ["Ashby boards yield well"],
                "recommended_next_searches": ["Focus buy-side market risk"],
            }
        )

        state = apply_strategy_patch(
            None,
            patch,
            workspace_id="ws_loop",
            reflection_run_id="run_reflect",
            reflection_task_id="task_reflect",
        )

        assert state.workspace_id == "ws_loop"
        assert state.recommended_next_searches == ["Focus buy-side market risk"]

        src_snap, prev_diag = materialize_discovery_hints(state)
        assert src_snap.known_boards == ["https://boards.greenhouse.io/acme"]
        assert prev_diag.recommended_next_searches == ["Focus buy-side market risk"]
        assert len(prev_diag.coverage_gaps) == 1

        task_spec = build_discovery_task_spec(
            discovery_intent=_minimal_discovery_intent(),
            search_depth="standard",
            artifacts_dir="/tmp/artifacts",
            run_id="run_search",
            task_id="task_search",
            source_registry_snapshot=src_snap,
            previous_run_diagnostics=prev_diag,
        )

        assert task_spec.source_registry_snapshot is not None
        assert task_spec.previous_run_diagnostics is not None
        assert task_spec.source_registry_snapshot.known_boards
        assert task_spec.previous_run_diagnostics.recommended_next_searches

    def test_db_json_roundtrip(self):
        state = SearchStrategyState(
            workspace_id="ws_rt",
            effective_sources=["lever.co/foo"],
            recommended_next_searches=["next"],
            last_reflection_run_id="run_1",
            last_reflection_task_id="task_1",
            updated_at=datetime.now(timezone.utc),
        )
        row_json = state_to_db_json(state)
        restored = state_from_db_row(
            workspace_id="ws_rt",
            profile_id=None,
            state_json=row_json,
            last_reflection_run_id="run_1",
            last_reflection_task_id="task_1",
            updated_at=state.updated_at,
        )
        assert restored.effective_sources == ["lever.co/foo"]
        assert restored.recommended_next_searches == ["next"]
