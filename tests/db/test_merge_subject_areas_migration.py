"""Tests for subject_areas migration merge logic."""

from __future__ import annotations

from packages.infrastructure.db.migrations.versions.m3n4o5p6q7r8_merge_subject_areas import (
    _merge_subject_areas,
)


class TestMergeSubjectAreas:
    def test_merge_dedupes_preserving_order(self):
        result = _merge_subject_areas(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_merge_strips_and_skips_empty(self):
        result = _merge_subject_areas(["  a  ", ""], ["  ", "b"])
        assert result == ["a", "b"]

    def test_merge_empty_sources_returns_none(self):
        assert _merge_subject_areas(None, None) is None
        assert _merge_subject_areas([], []) is None

    def test_merge_domain_only(self):
        result = _merge_subject_areas(["market risk"], None)
        assert result == ["market risk"]
