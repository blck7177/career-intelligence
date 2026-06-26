"""Tests for source_registry alias loading and normalization."""

from packages.domain.agent_jobs.source_registry import (
    _normalize_alias_key,
    get_source_type_aliases,
    load_source_type_aliases,
    normalize_source_type,
)


class TestNormalizeAliasKey:
    def test_strips_and_lower_cases(self):
        assert _normalize_alias_key("Goldman_Sachs") == "goldmansachs"


class TestLoadSourceTypeAliases:
    def test_loads_aliases_from_config(self):
        aliases = load_source_type_aliases()
        assert aliases["greenhouse"] == ("ats", "greenhouse")
        assert aliases["linkedin"] == ("job_board", "linkedin")
        assert aliases["jpmorgan"] == ("company_careers", "jpmorgan")

    def test_cached_singleton_matches_loader(self):
        assert get_source_type_aliases() == load_source_type_aliases()


class TestNormalizeSourceType:
    def test_known_ats_alias(self):
        assert normalize_source_type("Greenhouse") == ("ats", "greenhouse")

    def test_known_company_careers_alias(self):
        assert normalize_source_type("goldman_sachs") == (
            "company_careers",
            "goldman_sachs",
        )

    def test_unknown_short_brand_treated_as_company_careers(self):
        assert normalize_source_type("stripe") == ("company_careers", "stripe")

    def test_url_like_value_is_unknown(self):
        assert normalize_source_type("https://jobs.example.com/listing") == (
            "unknown",
            None,
        )
