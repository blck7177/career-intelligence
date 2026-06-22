"""
ToolLedgerEvent — schema for HMAC-signed platform tool events.

Written by agent tool wrappers (career_log_candidates.py,
career_write_manifest.py) via packages.infrastructure.tool_ledger.
Read by ToolLedgerValidator during the validation gate.

Hash chain boundary: per invocation_id.
  - Each invocation starts with prev_event_hash=None, sequence=1.
  - Subsequent events chain: prev_event_hash = previous event_hash.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ToolLedgerEvent(BaseModel):
    schema_version: str = "tool-ledger@1"
    event_id: str                          # "tevt_<uuid4>"
    invocation_id: str
    run_id: str
    task_id: str
    tool_name: str                         # "career_log_candidates" | "career_write_manifest"
    event_type: str                        # "candidate_log" | "manifest_write"
    status: str                            # "ok" | "failed"
    timestamp: str                         # ISO-8601
    sequence: int                          # 1-based within this invocation
    candidate_count: Optional[int] = None
    output_path: Optional[str] = None
    output_hash: Optional[str] = None     # "sha256:<hex>"
    prev_event_hash: Optional[str] = None  # None for first event in chain
    event_hash: str                        # sha256 of canonical JSON (without event_hash/signature)
    signature: str                         # hmac_sha256(SIGNING_KEY, event_hash)
    signed_at: str                         # ISO-8601
