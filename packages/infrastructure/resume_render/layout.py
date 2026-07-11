"""
Layout parameters for resume document generation.

Fixed single default for now — no auto-adjustment ladder yet (deferred:
render-time page-fit checking and margin/spacing retry are a separate,
not-yet-built follow-up). generate() always uses DEFAULT_LAYOUT unless a
caller passes an explicit override.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutConfig:
    font_name: str = "Calibri"
    body_size_pt: float = 11
    heading_size_pt: float = 12
    name_size_pt: float = 16
    margin_top_in: float = 0.5
    margin_bottom_in: float = 0.5
    margin_left_in: float = 0.75
    margin_right_in: float = 0.75


DEFAULT_LAYOUT = LayoutConfig()
