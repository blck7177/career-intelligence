"""
Unit tests for packages.infrastructure.tool_ledger.

Tests:
  - Sign → verify round-trip
  - Hash chain continuity (3 events)
  - Wrong key → verify fails
  - Missing TOOL_LEDGER_SIGNING_KEY → wrappers emit no event (graceful skip)
  - load_and_verify: valid chain → no errors
  - load_and_verify: tampered signature → error
  - load_and_verify: broken prev_event_hash → error
  - load_and_verify: missing file → error
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.contracts.agents.tool_events import ToolLedgerEvent
from packages.infrastructure.tool_ledger import (
    append_signed_event,
    compute_event_hash,
    load_and_verify,
    sign_event_hash,
    verify_event,
)

_KEY = "test-signing-key-at-least-32-bytes-long!!"
_KEY_OTHER = "other-signing-key-at-least-32-bytes!!"

_BASE_FIELDS = {
    "invocation_id": "ainv_abc123",
    "run_id": "run_001",
    "task_id": "task_001",
    "tool_name": "career_log_candidates",
    "event_type": "candidate_log",
    "status": "ok",
    "candidate_count": 5,
}


# ---------------------------------------------------------------------------
# compute_event_hash / sign_event_hash
# ---------------------------------------------------------------------------


class TestCryptoHelpers:
    def test_compute_event_hash_is_deterministic(self):
        data = {"a": 1, "b": "hello", "c": None}
        assert compute_event_hash(data) == compute_event_hash(data)

    def test_compute_event_hash_ignores_event_hash_and_signature_fields(self):
        data = {"a": 1}
        data_with_extra = {"a": 1, "event_hash": "ignored", "signature": "ignored"}
        assert compute_event_hash(data) == compute_event_hash(data_with_extra)

    def test_compute_event_hash_changes_on_field_change(self):
        data_a = {"a": 1}
        data_b = {"a": 2}
        assert compute_event_hash(data_a) != compute_event_hash(data_b)

    def test_sign_event_hash_is_deterministic(self):
        h = compute_event_hash({"x": 42})
        assert sign_event_hash(h, _KEY) == sign_event_hash(h, _KEY)

    def test_sign_event_hash_differs_by_key(self):
        h = compute_event_hash({"x": 42})
        assert sign_event_hash(h, _KEY) != sign_event_hash(h, _KEY_OTHER)


# ---------------------------------------------------------------------------
# Sign → verify round-trip
# ---------------------------------------------------------------------------


class TestSignVerifyRoundtrip:
    def test_round_trip_single_event(self, tmp_path):
        ledger = tmp_path / "tool_events.jsonl"
        event = append_signed_event(ledger, _BASE_FIELDS, _KEY)
        assert event is not None
        assert verify_event(event, _KEY) is True

    def test_wrong_key_fails_verification(self, tmp_path):
        ledger = tmp_path / "tool_events.jsonl"
        event = append_signed_event(ledger, _BASE_FIELDS, _KEY)
        assert event is not None
        assert verify_event(event, _KEY_OTHER) is False

    def test_tampered_field_fails_verification(self, tmp_path):
        ledger = tmp_path / "tool_events.jsonl"
        event = append_signed_event(ledger, _BASE_FIELDS, _KEY)
        assert event is not None
        # Tamper with a field
        tampered = event.model_copy(update={"candidate_count": 9999})
        assert verify_event(tampered, _KEY) is False


# ---------------------------------------------------------------------------
# Hash chain continuity
# ---------------------------------------------------------------------------


class TestHashChainContinuity:
    def test_three_event_chain(self, tmp_path):
        """Three events chained correctly: prev_event_hash links form an unbroken chain."""
        ledger = tmp_path / "tool_events.jsonl"
        fields = dict(_BASE_FIELDS)

        ev1 = append_signed_event(ledger, fields, _KEY)
        ev2 = append_signed_event(ledger, fields, _KEY)
        ev3 = append_signed_event(ledger, fields, _KEY)

        assert ev1 is not None
        assert ev2 is not None
        assert ev3 is not None

        assert ev1.sequence == 1
        assert ev2.sequence == 2
        assert ev3.sequence == 3

        assert ev1.prev_event_hash is None
        assert ev2.prev_event_hash == ev1.event_hash
        assert ev3.prev_event_hash == ev2.event_hash

    def test_load_and_verify_valid_chain(self, tmp_path):
        ledger = tmp_path / "tool_events.jsonl"
        for _ in range(3):
            append_signed_event(ledger, _BASE_FIELDS, _KEY)

        events, errors = load_and_verify(ledger, "ainv_abc123", _KEY)
        assert errors == []
        assert len(events) == 3

    def test_chain_resets_per_invocation(self, tmp_path):
        """A second invocation in the same file starts a fresh chain."""
        ledger = tmp_path / "tool_events.jsonl"
        fields_a = dict(_BASE_FIELDS, invocation_id="ainv_A")
        fields_b = dict(_BASE_FIELDS, invocation_id="ainv_B")

        append_signed_event(ledger, fields_a, _KEY)
        append_signed_event(ledger, fields_b, _KEY)
        append_signed_event(ledger, fields_a, _KEY)  # 2nd event for invocation A

        events_a, errors_a = load_and_verify(ledger, "ainv_A", _KEY)
        events_b, errors_b = load_and_verify(ledger, "ainv_B", _KEY)

        assert errors_a == []
        assert len(events_a) == 2
        assert events_a[0].prev_event_hash is None

        assert errors_b == []
        assert len(events_b) == 1
        assert events_b[0].prev_event_hash is None


# ---------------------------------------------------------------------------
# load_and_verify error cases
# ---------------------------------------------------------------------------


class TestLoadAndVerify:
    def test_missing_file_returns_error(self, tmp_path):
        ledger = tmp_path / "nonexistent.jsonl"
        events, errors = load_and_verify(ledger, "ainv_abc123", _KEY)
        assert events == []
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_bad_signature_returns_error(self, tmp_path):
        ledger = tmp_path / "tool_events.jsonl"
        append_signed_event(ledger, _BASE_FIELDS, _KEY)

        # Tamper with the signature in the file (Pydantic uses compact JSON — no space after colon)
        content = ledger.read_text()
        import re
        content = re.sub(r'"signature":\s*"[^"]*"', '"signature":"deadbeef"', content)
        ledger.write_text(content)

        events, errors = load_and_verify(ledger, "ainv_abc123", _KEY)
        assert len(errors) > 0
        assert any("signature" in e or "hash" in e for e in errors)

    def test_broken_prev_event_hash_returns_error(self, tmp_path):
        ledger = tmp_path / "tool_events.jsonl"
        append_signed_event(ledger, _BASE_FIELDS, _KEY)
        append_signed_event(ledger, _BASE_FIELDS, _KEY)

        # Break the chain in the second event
        lines = ledger.read_text().splitlines()
        second = json.loads(lines[1])
        second["prev_event_hash"] = "aaaa" * 16
        lines[1] = json.dumps(second)
        ledger.write_text("\n".join(lines) + "\n")

        events, errors = load_and_verify(ledger, "ainv_abc123", _KEY)
        assert len(errors) > 0
        # At minimum a chain error (possibly also a signature error since we mutated the event)
        assert any("chain" in e or "signature" in e or "hash" in e for e in errors)

    def test_wrong_signing_key_returns_errors(self, tmp_path):
        """Events signed with _KEY but verified with _KEY_OTHER → errors."""
        ledger = tmp_path / "tool_events.jsonl"
        append_signed_event(ledger, _BASE_FIELDS, _KEY)

        events, errors = load_and_verify(ledger, "ainv_abc123", _KEY_OTHER)
        assert len(errors) > 0

    def test_empty_invocation_returns_no_events_no_errors(self, tmp_path):
        """File exists but no events for this invocation → no errors."""
        ledger = tmp_path / "tool_events.jsonl"
        # Write event for a different invocation
        append_signed_event(ledger, dict(_BASE_FIELDS, invocation_id="ainv_other"), _KEY)

        events, errors = load_and_verify(ledger, "ainv_abc123", _KEY)
        assert events == []
        assert errors == []  # no events for this invocation — not an error at this layer


# ---------------------------------------------------------------------------
# Missing TOOL_LEDGER_SIGNING_KEY → graceful skip
# ---------------------------------------------------------------------------


class TestMissingSigningKey:
    def test_append_signed_event_skips_when_no_key(self, tmp_path):
        """append_signed_event returns None and writes nothing when signing_key is empty."""
        ledger = tmp_path / "tool_events.jsonl"
        result = append_signed_event(ledger, _BASE_FIELDS, signing_key="")
        assert result is None
        assert not ledger.exists()
