"""Tests for tier quota loading and lookup."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from packages.domain.quota.tiers import (
    FALLBACK_TIER,
    QuotaRule,
    get_quota_rule,
    load_quotas,
)


class TestLoadQuotasAgainstRealConfig:
    """The actual configs/quotas.yaml shipped with this repo."""

    def test_new_tier_restricts_job_discovery_to_quick(self):
        quotas = load_quotas()
        rule = quotas["new"]["job_discovery"]
        assert rule.monthly_limit == 10
        assert rule.allowed_search_depth == ("quick",)

    def test_pro_tier_allows_quick_and_standard_not_deep(self):
        quotas = load_quotas()
        rule = quotas["pro"]["job_discovery"]
        assert rule.monthly_limit == 30
        assert "deep" not in rule.allowed_search_depth

    def test_max_tier_allows_deep(self):
        quotas = load_quotas()
        rule = quotas["max"]["job_discovery"]
        assert rule.monthly_limit == 100
        assert "deep" in rule.allowed_search_depth

    def test_beta_job_discovery_matches_pro(self):
        quotas = load_quotas()
        assert quotas["beta"]["job_discovery"] == quotas["pro"]["job_discovery"]

    def test_beta_has_no_rule_for_other_run_types(self):
        quotas = load_quotas()
        assert "job_report" not in quotas["beta"]
        assert "resume_tailor" not in quotas["beta"]


class TestLoadQuotasFileHandling:
    def test_missing_file_returns_empty_dict(self, tmp_path: Path):
        assert load_quotas(tmp_path / "does_not_exist.yaml") == {}

    def test_malformed_yaml_returns_empty_dict(self, tmp_path: Path):
        bad = tmp_path / "quotas.yaml"
        bad.write_text("tiers: [this, is, not, a, mapping")
        assert load_quotas(bad) == {}

    def test_custom_path_parses_correctly(self, tmp_path: Path):
        custom = tmp_path / "quotas.yaml"
        custom.write_text(
            textwrap.dedent(
                """
                tiers:
                  widget:
                    job_discovery: { monthly_limit: 7, allowed_search_depth: [quick] }
                """
            )
        )
        quotas = load_quotas(custom)
        assert quotas["widget"]["job_discovery"] == QuotaRule(
            monthly_limit=7, allowed_search_depth=("quick",)
        )


class TestGetQuotaRule:
    def test_known_tier_and_run_type(self):
        rule = get_quota_rule("new", "job_discovery")
        assert rule is not None
        assert rule.monthly_limit == 10

    def test_unconfigured_run_type_is_unlimited(self):
        # "beta" has no candidate_story_build entry -> unlimited by convention
        assert get_quota_rule("beta", "candidate_story_build") is None

    def test_unknown_tier_falls_back_to_new(self):
        assert get_quota_rule("nonexistent_tier", "job_discovery") == get_quota_rule(
            FALLBACK_TIER, "job_discovery"
        )
