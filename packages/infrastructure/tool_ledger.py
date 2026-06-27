"""
Tool Ledger — HMAC-signed append-only event log for platform wrappers.

Wrappers write one ToolLedgerEvent per invocation to tool_events.jsonl.
ToolLedgerValidator reads and verifies the chain during the validator gate.

Hash chain boundary: per invocation_id.
  - First event in a chain: prev_event_hash=None, sequence=1.
  - Each subsequent event: prev_event_hash = previous event's event_hash.

Signing key: TOOL_LEDGER_SIGNING_KEY env var (min 32 bytes recommended).
Missing key → wrappers emit no event (graceful skip with WARNING log).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from packages.contracts.agents.tool_events import ToolLedgerEvent

logger = logging.getLogger(__name__)

# Fields excluded from the event_hash computation so the hash is stable.
_HASH_EXCLUDED_FIELDS = frozenset({"event_hash", "signature"})


# ---------------------------------------------------------------------------
# Core crypto helpers
# ---------------------------------------------------------------------------


def compute_event_hash(event_data: dict) -> str:
    """
    Compute sha256 of the canonical JSON representation of event_data.

    Canonical form: JSON with sorted keys, excluding event_hash and signature
    fields (which are set after hashing). Encoding: UTF-8.
    """
    canonical = {k: v for k, v in event_data.items() if k not in _HASH_EXCLUDED_FIELDS}
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def sign_event_hash(event_hash: str, key: str) -> str:
    """
    Compute HMAC-SHA256 of event_hash using key.

    Returns the hexdigest string.
    """
    return hmac.new(
        key.encode("utf-8"),
        event_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_event(event: ToolLedgerEvent, key: str) -> bool:
    """
    Verify that event_hash and signature are internally consistent.

    Returns True if both are valid; False otherwise.
    Does not raise — callers should treat False as a tamper signal.
    """
    try:
        expected_hash = compute_event_hash(event.model_dump())
        if expected_hash != event.event_hash:
            return False
        expected_sig = sign_event_hash(event.event_hash, key)
        return hmac.compare_digest(expected_sig, event.signature)
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Append helper
# ---------------------------------------------------------------------------


def append_signed_event(
    ledger_path: Path,
    fields: dict,
    signing_key: str,
) -> Optional[ToolLedgerEvent]:
    """
    Build, sign, and append one ToolLedgerEvent to ledger_path.

    ``fields`` must include at minimum:
      invocation_id, run_id, task_id, tool_name, event_type, status

    The function reads existing events from ledger_path (if the file exists)
    filtered to the same invocation_id to determine prev_event_hash and
    sequence.  Thread-safety: this is a single-writer-per-invocation design;
    concurrent appends from different processes to the same file are not safe.

    Returns the signed ToolLedgerEvent on success, or None on error (with a
    WARNING log).  Never raises — callers should treat None as a graceful skip.
    """
    if not signing_key:
        logger.warning(
            "tool_ledger: TOOL_LEDGER_SIGNING_KEY is not set — skipping signed event for %s",
            fields.get("tool_name", "unknown"),
        )
        return None

    try:
        invocation_id = fields["invocation_id"]
        existing = _read_events_for_invocation(ledger_path, invocation_id)

        prev_event_hash: Optional[str] = None
        sequence = 1
        if existing:
            last = existing[-1]
            prev_event_hash = last.event_hash
            sequence = last.sequence + 1

        now = datetime.now(timezone.utc).isoformat()
        event_id = f"tevt_{uuid.uuid4()}"

        raw: dict = {
            "schema_version": "tool-ledger@1",
            "event_id": event_id,
            "invocation_id": invocation_id,
            "run_id": fields.get("run_id", ""),
            "task_id": fields.get("task_id", ""),
            "tool_name": fields.get("tool_name", ""),
            "event_type": fields.get("event_type", ""),
            "status": fields.get("status", "ok"),
            "timestamp": now,
            "sequence": sequence,
            "candidate_count": fields.get("candidate_count"),
            "output_path": fields.get("output_path"),
            "output_hash": fields.get("output_hash"),
            "prev_event_hash": prev_event_hash,
            "signed_at": now,
        }

        event_hash = compute_event_hash(raw)
        signature = sign_event_hash(event_hash, signing_key)

        raw["event_hash"] = event_hash
        raw["signature"] = signature

        event = ToolLedgerEvent.model_validate(raw)

        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a") as f:
            f.write(event.model_dump_json() + "\n")

        logger.debug(
            "tool_ledger: appended %s event seq=%d to %s",
            event.event_type,
            sequence,
            ledger_path,
        )
        return event

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "tool_ledger: failed to append signed event for %s: %s",
            fields.get("tool_name", "unknown"),
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Load and verify
# ---------------------------------------------------------------------------


def load_and_verify(
    ledger_path: Path,
    invocation_id: str,
    signing_key: str,
) -> tuple[list[ToolLedgerEvent], list[str]]:
    """
    Load all events for invocation_id from ledger_path and verify integrity.

    Returns (events, errors) where:
      - events: list of ToolLedgerEvent in sequence order (may be empty on error)
      - errors: list of human-readable error strings (empty = all good)

    Verifications performed:
      1. Signature: HMAC-SHA256(key, event_hash) matches event.signature
      2. Hash integrity: compute_event_hash(event) matches event.event_hash
      3. Chain continuity: each event's prev_event_hash matches the previous
         event's event_hash (first event must have prev_event_hash=None)
      4. Sequence monotonicity: sequence increases by 1 each step
    """
    errors: list[str] = []
    events: list[ToolLedgerEvent] = []

    if not ledger_path.exists():
        errors.append(f"tool_events.jsonl not found at {ledger_path}")
        return events, errors

    try:
        raw_lines = ledger_path.read_text().splitlines()
    except OSError as exc:
        errors.append(f"Could not read {ledger_path}: {exc}")
        return events, errors

    for lineno, line in enumerate(raw_lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            event = ToolLedgerEvent.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Line {lineno}: parse error: {exc}")
            continue

        if event.invocation_id != invocation_id:
            continue  # belongs to a different invocation

        events.append(event)

    if not events:
        return events, errors  # no events for this invocation — caller decides if that's an error

    # Sort by sequence to be safe
    events.sort(key=lambda e: e.sequence)

    prev_hash: Optional[str] = None
    for i, event in enumerate(events, 1):
        # 1. Verify hash integrity + signature
        if not verify_event(event, signing_key):
            errors.append(
                f"Event seq={event.sequence} id={event.event_id}: "
                "signature or hash verification failed"
            )

        # 2. Verify chain continuity
        if event.prev_event_hash != prev_hash:
            errors.append(
                f"Event seq={event.sequence} id={event.event_id}: "
                f"hash chain broken — expected prev_event_hash={prev_hash!r}, "
                f"got {event.prev_event_hash!r}"
            )

        # 3. Verify sequence monotonicity
        if event.sequence != i:
            errors.append(
                f"Event id={event.event_id}: expected sequence={i}, got {event.sequence}"
            )

        prev_hash = event.event_hash

    return events, errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_events_for_invocation(
    ledger_path: Path,
    invocation_id: str,
) -> list[ToolLedgerEvent]:
    """Read existing events for invocation_id (ignores parse errors for robustness)."""
    if not ledger_path.exists():
        return []
    events: list[ToolLedgerEvent] = []
    try:
        for line in ledger_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                event = ToolLedgerEvent.model_validate(raw)
                if event.invocation_id == invocation_id:
                    events.append(event)
            except Exception:  # noqa: BLE001
                pass
    except OSError:
        pass
    events.sort(key=lambda e: e.sequence)
    return events
