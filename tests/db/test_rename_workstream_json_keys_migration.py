"""Tests for role category JSON key migration remap logic."""

from packages.infrastructure.db.migrations.versions.m4n5o6p7q8r9_rename_workstream_json_keys import (
    _remap_keys,
)


class TestRemapWorkstreamKeys:
    def test_remaps_structured_fields(self):
        src = {
            "primary_workstream": "Market Risk / Exposure Monitoring",
            "secondary_workstreams": ["Stress Testing / Scenario Analysis"],
            "workstream_evidence": ["VaR reporting"],
            "workstream_confidence": "high",
            "analyst_notes": "note",
        }
        out = _remap_keys(src)
        assert out == {
            "primary_role_category": "Market Risk / Exposure Monitoring",
            "secondary_role_categories": ["Stress Testing / Scenario Analysis"],
            "role_category_evidence": ["VaR reporting"],
            "role_category_confidence": "high",
            "analyst_notes": "note",
        }

    def test_leaves_unknown_keys(self):
        assert _remap_keys({"position_function": {}}) == {"position_function": {}}

    def test_none_passthrough(self):
        assert _remap_keys(None) is None
