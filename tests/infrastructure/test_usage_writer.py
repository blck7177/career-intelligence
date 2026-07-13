"""
Tests for usage_writer.py — estimate_cost() cache-token discount and the
persist_usage/persist_agent_usage failure-logging level.

Regression coverage for a 2026-07-12 accounting-gap audit: estimate_cost()
previously ignored cache_read_tokens entirely, billing 100% of prompt_tokens
at the full input rate even when the majority were cache hits (observed:
95% cache hit rate on a real run, ~8% cost overestimate at that ratio, worse
at higher cache-hit ratios). Also covers the silent-except log level bump
from WARNING to ERROR, since a swallowed DB write silently drops an
already-correctly-computed cost with no operator-visible signal otherwise.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from packages.infrastructure.llm.usage_writer import (
    estimate_cost,
    persist_agent_usage,
    persist_usage,
)


class TestEstimateCostCacheDiscount:
    def test_no_cache_matches_pre_existing_behavior(self):
        cost = estimate_cost("gpt-5.4-mini", 1_000_000, 1_000_000)
        assert cost == 0.15 + 0.60

    def test_full_cache_bills_at_half_input_rate(self):
        cost = estimate_cost("gpt-5.4-mini", 1_000_000, 0, cache_read_tokens=1_000_000)
        assert cost == 0.15 * 0.5

    def test_partial_cache_matches_real_observed_run(self):
        """Real numbers from the 2026-07-12 test run's original call."""
        cost = estimate_cost(
            "gpt-5.4-mini",
            prompt_tokens=1_002_430,
            completion_tokens=8_175,
            cache_read_tokens=955_392,
        )
        non_cached = 1_002_430 - 955_392
        expected = (
            non_cached * 0.15 / 1_000_000
            + 955_392 * 0.15 * 0.5 / 1_000_000
            + 8_175 * 0.60 / 1_000_000
        )
        assert cost == expected
        # Sanity: discounted cost must be strictly less than the old
        # no-discount calculation for the same tokens.
        old_no_discount = 1_002_430 * 0.15 / 1_000_000 + 8_175 * 0.60 / 1_000_000
        assert cost < old_no_discount

    def test_cache_read_tokens_clamped_to_prompt_tokens(self):
        """Defensive: a caller-supplied cache count that exceeds prompt_tokens
        (malformed upstream data) must not produce a negative non-cached
        portion or an inflated discount."""
        cost = estimate_cost("gpt-5.4-mini", 100, 0, cache_read_tokens=10_000)
        assert cost == 100 * 0.15 * 0.5 / 1_000_000

    def test_negative_cache_read_tokens_clamped_to_zero(self):
        cost = estimate_cost("gpt-5.4-mini", 100, 0, cache_read_tokens=-5)
        assert cost == 100 * 0.15 / 1_000_000

    def test_unknown_model_returns_none(self):
        assert estimate_cost("some-unlisted-model", 100, 100, cache_read_tokens=10) is None

    def test_default_cache_read_tokens_is_zero(self):
        assert estimate_cost("gpt-5.4-mini", 1000, 500) == estimate_cost(
            "gpt-5.4-mini", 1000, 500, cache_read_tokens=0
        )


@contextmanager
def _fake_get_session(mock_session):
    yield mock_session


class TestPersistAgentUsagePassesCacheThrough:
    def test_estimated_cost_reflects_cache_discount(self):
        mock_session = MagicMock()
        with patch(
            "packages.infrastructure.db.session.get_session",
            lambda: _fake_get_session(mock_session),
        ):
            persist_agent_usage(
                run_id="run_1",
                task_id="task_1",
                workspace_id="ws_1",
                call_site="agent.job_discovery",
                model="gpt-5.4-mini",
                input_tokens=1_000_000,
                output_tokens=0,
                cache_read_tokens=1_000_000,
            )
        assert mock_session.add.called
        event = mock_session.add.call_args[0][0]
        assert event.estimated_cost_usd == 0.15 * 0.5

    def test_default_cache_read_tokens_matches_no_discount(self):
        mock_session = MagicMock()
        with patch(
            "packages.infrastructure.db.session.get_session",
            lambda: _fake_get_session(mock_session),
        ):
            persist_agent_usage(
                run_id="run_1",
                task_id="task_1",
                workspace_id="ws_1",
                call_site="agent.job_discovery",
                model="gpt-5.4-mini",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
            )
        event = mock_session.add.call_args[0][0]
        assert event.estimated_cost_usd == 0.15 + 0.60


class TestSilentFailureIsLoggedAtErrorLevel:
    def test_persist_agent_usage_db_failure_logs_at_error(self, caplog):
        def boom():
            raise RuntimeError("db unavailable")

        with patch("packages.infrastructure.db.session.get_session", boom):
            with caplog.at_level(logging.ERROR, logger="packages.infrastructure.llm.usage_writer"):
                persist_agent_usage(
                    run_id="run_1",
                    task_id="task_1",
                    workspace_id="ws_1",
                    call_site="agent.job_discovery",
                    model="gpt-5.4-mini",
                    input_tokens=100,
                    output_tokens=50,
                )
        assert any(r.levelno == logging.ERROR for r in caplog.records)
        assert any("cost NOT recorded" in r.message for r in caplog.records)

    def test_persist_usage_db_failure_logs_at_error(self, caplog):
        def boom():
            raise RuntimeError("db unavailable")

        with patch("packages.infrastructure.db.session.get_session", boom):
            with caplog.at_level(logging.ERROR, logger="packages.infrastructure.llm.usage_writer"):
                persist_usage(
                    model="gpt-5.4-mini",
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                )
        assert any(r.levelno == logging.ERROR for r in caplog.records)
        assert any("cost NOT recorded" in r.message for r in caplog.records)
