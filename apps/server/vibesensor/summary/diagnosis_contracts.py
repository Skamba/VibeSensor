"""Persisted/HTTP contract for the run diagnosis the UI and the PDF both show.

The analysis computes this block once per run (``vibesensor.analysis.diagnosis``).
Consumers translate it; they never re-derive the verdict, the confidence level,
order labels, amplitudes, or zones.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import ConfigDict, with_config

__all__ = [
    "AmplitudeBasis",
    "ConfidenceLevelValue",
    "DiagnosisPayload",
    "DiagnosisSpectrum",
    "DiagnosisVerdictValue",
    "LocationAmplitudeRow",
    "OrderCodeValue",
    "OrderFindingRow",
    "RpmSourceValue",
    "SourceCheck",
    "SourceCheckReason",
    "SourceCheckStatus",
    "SpectrumPeak",
    "SpeedAmplitudePoint",
    "TestConditions",
]

_FORBID_EXTRA = ConfigDict(extra="forbid")

type DiagnosisVerdictValue = Literal["fault", "weak_evidence", "no_fault"]
type ConfidenceLevelValue = Literal["strong", "moderate", "weak"]
type OrderCodeValue = Literal["T1", "T2", "P1", "P2", "E1", "E2"]
type AmplitudeBasis = Literal["order", "overall"]
type SourceCheckStatus = Literal["candidate", "ruled_out", "not_testable"]
type SourceCheckReason = Literal[
    "no_tire_reference",
    "no_drive_reference",
    "no_engine_reference",
    "rpm_estimated",
    "no_matching_order",
]
type RpmSourceValue = Literal["measured", "estimated", "none"]


@with_config(_FORBID_EXTRA)
class LocationAmplitudeRow(TypedDict):
    """Amplitude at one sensor location (mg, with dB above that location's floor)."""

    location: str
    amplitude_mg: float | None
    db_above_floor: float | None
    ratio_to_strongest: float | None
    presence_ratio: float | None


@with_config(_FORBID_EXTRA)
class SpeedAmplitudePoint(TypedDict):
    """Median amplitude of the diagnosed order in one 5 km/h speed bin at one location."""

    speed_kmh: float
    location: str
    amplitude_mg: float


@with_config(_FORBID_EXTRA)
class SpectrumPeak(TypedDict):
    """One recurring spectral peak (0.5 Hz bin) and its median amplitude."""

    hz: float
    amplitude_mg: float


@with_config(_FORBID_EXTRA)
class DiagnosisSpectrum(TypedDict):
    """Recurring peaks at one location within one speed window, with order markers."""

    location: str
    speed_min_kmh: float
    speed_max_kmh: float
    floor_mg: float | None
    peaks: list[SpectrumPeak]
    order_markers: dict[str, float]


@with_config(_FORBID_EXTRA)
class OrderFindingRow(TypedDict):
    """One order-tracked finding as a workshop worksheet row."""

    finding_id: str
    source: str
    order_code: OrderCodeValue
    location: str | None
    frequency_hz: float | None
    reference_speed_kmh: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    phases: list[str]
    presence_ratio: float | None
    confidence_level: ConfidenceLevelValue


@with_config(_FORBID_EXTRA)
class SourceCheck(TypedDict):
    """Whether one source family was the candidate, ruled out, or not testable."""

    source: str
    status: SourceCheckStatus
    reason: SourceCheckReason | None


@with_config(_FORBID_EXTRA)
class TestConditions(TypedDict):
    """Reference data the order analysis used."""

    speed_source: str | None
    rpm_source: RpmSourceValue
    tire_circumference_m: float | None
    final_drive_ratio: float | None
    gear_ratio: float | None


@with_config(_FORBID_EXTRA)
class DiagnosisPayload(TypedDict):
    """The run verdict, its single confidence level, and the evidence behind it."""

    verdict: DiagnosisVerdictValue
    confidence_level: ConfidenceLevelValue | None
    finding_id: str | None
    source: str | None
    location: str | None
    zone: str | None
    order_code: OrderCodeValue | None
    frequency_hz: float | None
    reference_speed_kmh: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    dominant_phase: str | None
    presence_ratio: float | None
    weak_reasons: list[str]
    order_findings: list[OrderFindingRow]
    amplitude_basis: AmplitudeBasis
    location_amplitudes: list[LocationAmplitudeRow]
    amplitude_vs_speed: list[SpeedAmplitudePoint]
    spectrum: DiagnosisSpectrum | None
    source_checks: list[SourceCheck]
    conditions: TestConditions
