"""
SourceRegistry — loads agent source_type alias map from configs/source_registry.yaml.

Maps brand names and platform aliases to canonical (source_type, source_provider)
pairs when persisting agent-discovered job records.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "source_registry.yaml"
)


def _normalize_alias_key(raw: str) -> str:
    return raw.lower().replace(" ", "").replace("-", "").replace("_", "")


def load_source_type_aliases(
    registry_path: Path | None = None,
) -> dict[str, tuple[str, str]]:
    """
    Load alias → (source_type, source_provider) map from YAML.

    Returns empty dict if file not found or parse fails.
    """
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed; source registry unavailable")
        return {}

    path = registry_path or _DEFAULT_REGISTRY_PATH
    if not path.exists():
        logger.warning("Source registry not found at %s", path)
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        aliases = data.get("aliases", {}) if isinstance(data, dict) else {}
        result: dict[str, tuple[str, str]] = {}
        for key, entry in aliases.items():
            if not isinstance(entry, dict):
                continue
            source_type = entry.get("source_type")
            source_provider = entry.get("source_provider")
            if source_type and source_provider:
                result[_normalize_alias_key(str(key))] = (source_type, source_provider)
        logger.debug("Loaded %d source aliases from %s", len(result), path)
        return result
    except Exception as exc:
        logger.warning("Failed to load source registry from %s: %s", path, exc)
        return {}


@lru_cache(maxsize=1)
def get_source_type_aliases() -> dict[str, tuple[str, str]]:
    """Cached singleton. Use in production code."""
    return load_source_type_aliases()


def normalize_source_type(
    raw: str,
    aliases: dict[str, tuple[str, str]] | None = None,
) -> tuple[str, str | None]:
    """
    Map agent-supplied source_type to (canonical_type, provider).

    canonical_type: company_careers | ats | job_board | unknown
    provider: brand/platform name or None
    """
    alias_map = aliases if aliases is not None else get_source_type_aliases()
    key = _normalize_alias_key(raw)
    if key in alias_map:
        return alias_map[key]
    if raw and len(raw) < 40 and "/" not in raw:
        return ("company_careers", raw.lower())
    return ("unknown", None)
