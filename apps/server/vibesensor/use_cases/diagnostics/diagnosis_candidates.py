"""Boundary helpers for filtering and selecting diagnosis candidates."""

from __future__ import annotations


def normalize_origin_location(location: object) -> str:
    """Normalize the analysis placeholder ``unknown`` to an empty string."""
    normalized = str(location or "").strip()
    return "" if normalized.lower() == "unknown" else normalized
