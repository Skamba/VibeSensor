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
    "FuelTypeValue",
    "GuidedPhaseValue",
    "LocationAmplitudeRow",
    "OrderCodeValue",
    "OrderFindingRow",
    "ReferenceProvenanceValue",
    "RpmSourceValue",
    "SourceCheck",
    "SourceCheckReason",
    "SourceCheckStatus",
    "SpeedDependenceValue",
    "SpectrumPeak",
    "SpeedAmplitudePoint",
    "TestConditions",
]

_FORBID_EXTRA = ConfigDict(extra="forbid")

type DiagnosisVerdictValue = Literal["fault", "weak_evidence", "no_fault"]
type ConfidenceLevelValue = Literal["strong", "moderate", "weak"]
type OrderCodeValue = Literal["T1", "T2", "P1", "P2", "E1", "E2"]
type AmplitudeBasis = Literal["order", "overall"]
# ``ruled_out_estimated``: no match, but the order rests on an estimate (a weak
# library ratio, or engine RPM estimated from speed assuming top gear).
type SourceCheckStatus = Literal["candidate", "ruled_out", "ruled_out_estimated", "not_testable"]
type SourceCheckReason = Literal[
    "no_tire_reference",
    "no_drive_reference",
    "no_engine_reference",
    "manual_speed",
    "top_gear_assumed",
    "estimated_final_drive",
    "estimated_top_gear",
    "no_matching_order",
    "stayed_in_neutral",
    "stopped_in_neutral",
]
type GuidedPhaseValue = Literal["sweep", "hold", "coast_down"]
type SpeedDependenceValue = Literal["vehicle_speed", "engine_speed"]
type RpmSourceValue = Literal["measured", "estimated_top_gear", "none"]
# Where a car reference came from: the user, a car-library confidence, or missing.
type ReferenceProvenanceValue = Literal[
    "user_confirmed",
    "official_exact",
    "official_derived",
    "reputable_secondary_crosschecked",
    "family_default",
    "unverified",
    "missing",
]
type FuelTypeValue = Literal["ICE", "PHEV", "EV"]


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
    """Reference data the order analysis used, with where each reference came from."""

    speed_source: str | None
    rpm_source: RpmSourceValue
    tire_circumference_m: float | None
    final_drive_ratio: float | None
    gear_ratio: float | None
    tire_provenance: ReferenceProvenanceValue
    final_drive_provenance: ReferenceProvenanceValue
    gear_ratio_provenance: ReferenceProvenanceValue
    fuel_type: FuelTypeValue | None


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
    # Share of the moving drive in which the diagnosed order was there (any sensor).
    presence_ratio: float | None
    weak_reasons: list[str]
    guided_phases: list[GuidedPhaseValue]
    speed_dependence: SpeedDependenceValue | None
    order_findings: list[OrderFindingRow]
    amplitude_basis: AmplitudeBasis
    location_amplitudes: list[LocationAmplitudeRow]
    amplitude_vs_speed: list[SpeedAmplitudePoint]
    spectrum: DiagnosisSpectrum | None
    source_checks: list[SourceCheck]
    conditions: TestConditions
