"""
Tier quota rules — loads per-tier, per-run_type monthly limits and allowed
search_depth values from configs/quotas.yaml.

Pure function (reads a static config file). No DB, no LLM.

Two distinct fallback behaviors, both intentional:
  - quotas.yaml missing/unparseable entirely -> fail OPEN (unlimited for
    everyone). A config-loading bug should not lock out paying customers.
  - a workspace's tier value isn't a key in the (successfully loaded) file
    -> fall back to the "new" tier's rules (the most restrictive), since
    that indicates bad data on one workspace, not a global outage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_QUOTAS_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "quotas.yaml"
)

FALLBACK_TIER = "new"


@dataclass(frozen=True)
class QuotaRule:
    monthly_limit: int | None = None  # None = unlimited
    allowed_search_depth: tuple[str, ...] | None = None  # None = no restriction


def load_quotas(quotas_path: Path | None = None) -> dict[str, dict[str, QuotaRule]]:
    """
    Load tier quota rules from YAML.

    Returns {tier_name: {run_type: QuotaRule}}. Returns {} (fail-open —
    treated as unlimited by get_quota_rule) if the file is missing, PyYAML
    isn't installed, or parsing fails.
    """
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed; quota rules unavailable (fail-open)")
        return {}

    path = quotas_path or _DEFAULT_QUOTAS_PATH
    if not path.exists():
        logger.warning("Quotas file not found at %s; proceeding without quotas (fail-open)", path)
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        tiers_raw = (data or {}).get("tiers") or {}
        result: dict[str, dict[str, QuotaRule]] = {}
        for tier_name, run_types in tiers_raw.items():
            rules: dict[str, QuotaRule] = {}
            for run_type, rule in (run_types or {}).items():
                rule = rule or {}
                depth = rule.get("allowed_search_depth")
                rules[run_type] = QuotaRule(
                    monthly_limit=rule.get("monthly_limit"),
                    allowed_search_depth=tuple(depth) if depth else None,
                )
            result[tier_name] = rules
        return result
    except Exception as exc:
        logger.warning("Failed to load quotas from %s: %s (fail-open)", path, exc)
        return {}


@lru_cache(maxsize=1)
def _cached_quotas() -> dict[str, dict[str, QuotaRule]]:
    return load_quotas()


def get_quota_rule(tier: str, run_type: str) -> QuotaRule | None:
    """
    Return the QuotaRule for this tier+run_type.

    None means "no rule to enforce" (unlimited) — either because quotas.yaml
    itself is unavailable, or because this specific run_type has no entry
    under the resolved tier (an omitted run_type is always unlimited, by
    config convention — see configs/quotas.yaml's "beta" tier).
    """
    quotas = _cached_quotas()
    if not quotas:
        return None  # file missing/unparseable — fail open

    tier_rules = quotas.get(tier)
    if tier_rules is None:
        logger.warning(
            "Unknown workspace tier %r — falling back to %r quota rules", tier, FALLBACK_TIER
        )
        tier_rules = quotas.get(FALLBACK_TIER, {})
    return tier_rules.get(run_type)
