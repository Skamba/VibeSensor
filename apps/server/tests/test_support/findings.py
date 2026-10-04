"""Canonical finding-payload factories for tests.

All test modules that need ``FindingPayload`` dicts should import from here
instead of defining local ``_make_finding`` helpers.
"""

from __future__ import annotations

from dataclasses import replace

from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.summary.diagnosis_contracts import DiagnosisPayload
from vibesensor.summary.finding_payload_parts import FindingPayload


def make_finding(
    finding_id: str = "F_ORDER",
    suspected_source: VibrationSource | str = VibrationSource.WHEEL_TIRE,
    confidence: float | None = 0.75,
    severity: str = "",
    ranking_score: float = 1.0,
    strongest_location: str | None = None,
    **overrides: object,
) -> Finding:
    """Build a minimal domain ``Finding`` with sensible defaults."""
    base = Finding(
        finding_id=finding_id,
        suspected_source=suspected_source,
        confidence=confidence,
        severity=severity,
        ranking_score=ranking_score,
        strongest_location=strongest_location,
    )
    return replace(base, **overrides)


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
        "evidence_summary": "Test evidence summary",
        "frequency_hz_or_order": "1x wheel",
        "order": "1x wheel",
        "amplitude_metric": {
            "name": "vibration_strength_db",
            "value": 25.0,
            "units": "dB",
            "definition": {"_i18n_key": "METRIC"},
        },
        "confidence": confidence,
        "ranking_score": ranking_score,
    }
    if severity != "diagnostic":
        base["severity"] = severity
    if strongest_location is not None:
        base["strongest_location"] = strongest_location
    if overrides:
        base.update(overrides)
    if "order" not in overrides:
        if "frequency_hz" in overrides:
            base.pop("order", None)
        else:
            display_signal = base.get("frequency_hz_or_order")
            if isinstance(display_signal, str):
                base["order"] = display_signal
            elif isinstance(display_signal, (int, float)) and not isinstance(display_signal, bool):
                base["frequency_hz"] = float(display_signal)
                base.pop("order", None)
    return base


NO_FAULT_DIAGNOSIS: DiagnosisPayload = {
    "verdict": "no_fault",
    "confidence_level": None,
    "finding_id": None,
    "source": None,
    "location": None,
    "zone": None,
    "order_code": None,
    "frequency_hz": None,
    "reference_speed_kmh": None,
    "speed_min_kmh": None,
    "speed_max_kmh": None,
    "dominant_phase": None,
    "presence_ratio": None,
    "weak_reasons": [],
    "guided_phases": [],
    "speed_dependence": None,
    "order_findings": [],
    "amplitude_basis": "overall",
    "location_amplitudes": [],
    "amplitude_vs_speed": [],
    "spectrum": None,
    "source_checks": [],
    "conditions": {
        "speed_source": None,
        "rpm_source": "none",
        "tire_circumference_m": None,
        "final_drive_ratio": None,
        "gear_ratio": None,
        "tire_provenance": "missing",
        "final_drive_provenance": "missing",
        "gear_ratio_provenance": "missing",
        "fuel_type": None,
    },
}
