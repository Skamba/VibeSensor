"""Enums shared by the finding domain model."""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ConfidenceLevel",
    "DiagnosisVerdict",
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


class ConfidenceLevel(StrEnum):
    """Action-defined confidence in a diagnosis; the only confidence users see.

    ``STRONG``: go fix it. ``MODERATE``: do the cheap confirming check first.
    ``WEAK``: don't buy parts; record the test again.
    """

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class DiagnosisVerdict(StrEnum):
    """Run-level outcome shown identically by the UI and the PDF."""

    FAULT = "fault"
    WEAK_EVIDENCE = "weak_evidence"
    NO_FAULT = "no_fault"
