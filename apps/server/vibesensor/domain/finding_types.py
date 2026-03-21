"""Enums shared by the finding domain model."""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "FindingKind",
    "VibrationSource",
]


class VibrationSource(StrEnum):
    """Canonical mechanical vibration source categories.

    Compares equal to plain strings (``VibrationSource.ENGINE == "engine"``),
    so serialised payloads and dict-keyed lookups work naturally.
    """

    WHEEL_TIRE = "wheel/tire"
    DRIVELINE = "driveline"
    ENGINE = "engine"
    BODY_RESONANCE = "body resonance"
    TRANSIENT_IMPACT = "transient_impact"
    BASELINE_NOISE = "baseline_noise"
    UNKNOWN_RESONANCE = "unknown_resonance"
    UNKNOWN = "unknown"


class FindingKind(StrEnum):
    """Classification category of a diagnostic finding."""

    REFERENCE = "reference"
    INFORMATIONAL = "informational"
    DIAGNOSTIC = "diagnostic"
