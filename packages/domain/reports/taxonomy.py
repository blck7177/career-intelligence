"""
TaxonomyLoader — loads role category taxonomy from configs/role_category_taxonomy.yaml.

Pure function (reads a config file). No DB, no LLM.
The taxonomy is used by role_analyzer to:
  - Provide labels to Layer 1 (role archetype section)
  - Constrain Layer 2 primary_role_category to exact taxonomy labels
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "role_category_taxonomy.yaml"
)


def load_taxonomy(taxonomy_path: Path | None = None) -> list[dict[str, Any]]:
    """
    Load role category taxonomy from YAML.

    Returns list of category dicts with at minimum a 'label' key.
    Returns empty list (graceful degrade) if file not found or parse fails.
    """
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed; taxonomy unavailable")
        return []

    path = taxonomy_path or _DEFAULT_TAXONOMY_PATH
    if not path.exists():
        logger.warning("Taxonomy file not found at %s; proceeding without taxonomy", path)
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return []
        categories = data.get("role_categories") or []
        logger.debug("Loaded %d role categories from %s", len(categories), path)
        return categories
    except Exception as exc:
        logger.warning("Failed to load taxonomy from %s: %s", path, exc)
        return []


def get_taxonomy() -> list[dict[str, Any]]:
    """
    Re-reads configs/role_category_taxonomy.yaml on every call.

    Deliberately not cached: a cached read would keep serving a stale
    taxonomy for the life of the worker process after any edit to the
    YAML, silently rejecting valid role category ids (e.g. a mid-refactor
    key rename that lands in the file after the process already cached
    the old shape). Both call sites are per-request/per-patch, not a hot
    loop, so re-parsing this small file each time is cheap.
    """
    return load_taxonomy()
