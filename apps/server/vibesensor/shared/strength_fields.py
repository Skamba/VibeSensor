"""Shared vibration-strength field names for generated frontend constants."""

from __future__ import annotations

from typing import Final

METRIC_FIELDS: Final[dict[str, str]] = {
    "vibration_strength_db": "vibration_strength_db",
    "strength_bucket": "strength_bucket",
}

__all__ = ["METRIC_FIELDS"]
