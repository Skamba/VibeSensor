"""Canonical finding-payload factories for tests.

All test modules that need ``FindingPayload`` dicts should import from here
instead of defining local ``_make_finding`` helpers.
"""

from __future__ import annotations

from vibesensor.use_cases.diagnostics._types import FindingPayload


def make_finding_payload(
    finding_id: str = "F_ORDER",
    suspected_source: str = "wheel/tire",
    confidence: float | None = 0.75,
    severity: str = "diagnostic",
    ranking_score: float = 1.0,
    strongest_location: str | None = None,
    **overrides: object,
) -> FindingPayload:
    """Build a minimal ``FindingPayload`` dict with sensible defaults."""
    base: FindingPayload = {
        "finding_id": finding_id,
        "suspected_source": suspected_source,
        "evidence_summary": {"_i18n_key": "TEST"},
        "frequency_hz_or_order": "1x wheel",
        "amplitude_metric": {
            "name": "vibration_strength_db",
            "value": 25.0,
            "units": "dB",
            "definition": {"_i18n_key": "METRIC"},
        },
        "confidence": confidence,
        "quick_checks": [],
        "ranking_score": ranking_score,
    }
    if severity != "diagnostic":
        base["severity"] = severity
    if strongest_location is not None:
        base["strongest_location"] = strongest_location
    if overrides:
        base.update(overrides)  # type: ignore[typeddict-item]
    return base


def make_ref_finding(finding_id: str = "REF_SPEED", **overrides: object) -> FindingPayload:
    """Build a reference-type finding payload."""
    return make_finding_payload(
        finding_id=finding_id,
        suspected_source="unknown",
        confidence=None,
        severity="reference",
        ranking_score=0.0,
        **overrides,
    )


def make_info_finding(
    finding_id: str = "F_PEAK",
    confidence: float = 0.10,
    **overrides: object,
) -> FindingPayload:
    """Build an informational finding payload."""
    return make_finding_payload(
        finding_id=finding_id,
        suspected_source="transient_impact",
        confidence=confidence,
        severity="info",
        **overrides,
    )
