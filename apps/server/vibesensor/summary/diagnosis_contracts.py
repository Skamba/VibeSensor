"""Persisted/HTTP contract for the run diagnosis the UI and the PDF both show.

The analysis computes this block once per run (``vibesensor.analysis.diagnosis``).
Consumers translate it; they never re-derive the verdict, the confidence level,
order labels, amplitudes, or zones.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from pydantic import ConfigDict, with_config

from vibesensor.domain.engine_profile import EngineOrderRole, EngineProfilePayload

__all__ = [
    "AmplitudeBasis",
    "ConfidenceLevelValue",
    "DiagnosisPayload",
    "DiagnosisSpectrum",
    "DiagnosisVerdictValue",
    "DriveLayoutValue",
    "DiagnosisAlternative",
    "DrivelinePart",
    "EngineOrderRow",
    "FeltCauseRow",
    "FeltFallbackValue",
    "FeltPayload",
    "FeltSeverityValue",
    "FinalDriveAxleValue",
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
# Engine orders run in half orders: E1.5 is an inline-3's firing order, E8 a
# 16-cylinder's (domain/engine_profile.py).
type OrderCodeValue = Literal[
    "T1",
    "T2",
    "P1",
    "P2",
    "E0.5",
    "E1",
    "E1.5",
    "E2",
    "E2.5",
    "E3",
    "E3.5",
    "E4",
    "E4.5",
    "E5",
    "E5.5",
    "E6",
    "E6.5",
    "E7",
    "E7.5",
    "E8",
]
type AmplitudeBasis = Literal["order", "overall"]
# ``ruled_out_estimated``: no match, but the order rests on an estimate (a weak
# library ratio, engine RPM estimated from speed assuming top gear, a plug-in
# hybrid whose engine may have been off, or an EV/PHEV that may have braked on
# regeneration without its discs). ``not_applicable``: the car has no such
# source (an EV's engine). ``same_rhythm_as_candidate``: without measured RPM the
# engine turns at the diagnosed wheel or propshaft order's rhythm in some gear.
# ``faint_only`` (ruled out, no-fault runs): the order was found only below the
# moderate strength band, the residual a healthy car also has. ``speed_missing``:
# the live speed (GPS/OBD-II) was missing for most of the drive, so no
# road-speed order could be placed.
type SourceCheckStatus = Literal[
    "candidate", "ruled_out", "ruled_out_estimated", "not_testable", "not_applicable"
]
type SourceCheckReason = Literal[
    "no_tire_reference",
    "no_drive_reference",
    "no_engine_reference",
    "manual_speed",
    "speed_missing",
    "top_gear_assumed",
    "estimated_final_drive",
    "estimated_top_gear",
    "no_matching_order",
    "stayed_in_neutral",
    "stopped_in_neutral",
    "engine_may_be_off",
    "engine_not_running",
    "electric_car",
    "same_rhythm_as_candidate",
    "no_braking",
    "only_while_braking",
    "regen_braking",
    "faint_only",
]
# Why the causes stay ranked by evidence: no seat, trunk or tunnel sensor, or
# no order levels to read there (no raw capture).
type FeltFallbackValue = Literal["no_cabin_sensor", "no_order_levels"]
# A cause's level at the felt reference against its source's workshop limit
# (docs/metrics.md, "What the driver feels").
type FeltSeverityValue = Literal["workshop", "below_workshop", "normal"]
type GuidedPhaseValue = Literal["sweep", "hold", "coast_down", "brake"]
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
type DriveLayoutValue = Literal["FWD", "RWD", "AWD"]
type FinalDriveAxleValue = Literal["front", "rear"]
# The driveline parts a driveline-order fault points to, in the order to check
# them: the front axle's drive turning at wheel speed x final drive (without a
# propshaft the gearbox output shaft, final-drive pinion and differential
# bearings; on AWD the front propshaft and front differential pinion), or the
# propshaft and the rear axle's drive (joints, centre bearing, rear differential).
type DrivelinePart = Literal["front_drive", "propshaft_rear"]


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
class EngineOrderRow(TypedDict):
    """One engine order the run tested, and why the engine excites it."""

    code: OrderCodeValue
    # Empty when the engine is not known (E1/E2 tested without a profile).
    roles: list[EngineOrderRole]


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
    # The driven wheels; ``None`` (or absent, on runs analysed before it was
    # asked) when the owner did not say.
    drive_layout: NotRequired[DriveLayoutValue | None]
    # The axle the final drive belongs to (the driven one; AWD from the library).
    final_drive_axle: NotRequired[FinalDriveAxleValue | None]
    # Whether a propshaft drives the rear axle; ``None`` without a drive layout.
    propshaft: NotRequired[bool | None]
    # The engine's layout and cylinder count; ``None`` when not known, or for an
    # EV (absent on runs analysed before engines had one).
    engine_profile: NotRequired[EngineProfilePayload | None]
    # The engine orders the analysis tested (none for an EV).
    engine_orders: NotRequired[list[EngineOrderRow]]


@with_config(_FORBID_EXTRA)
class FeltCauseRow(TypedDict):
    """One cause's level at the felt reference sensor and how a workshop would judge it.

    ``level_mg`` is on the scale of ``location_amplitudes`` (0: the reference
    does not measure it); ``peak_mg`` the same level as the peak of a tone on
    one axis, the scale workshop limits are on (``workshop_mg``: from here a
    workshop repairs; ``normal_mg``: up to here it is normal; ``None`` without
    one). ``share`` is its part of what the causes heard at the same speeds
    shake there.
    """

    finding_id: str
    source: str
    order_codes: list[OrderCodeValue]
    level_mg: float
    peak_mg: float
    share: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    severity: FeltSeverityValue | None
    workshop_mg: float | None
    normal_mg: float | None


@with_config(_FORBID_EXTRA)
class FeltPayload(TypedDict):
    """The run's causes ranked by what the driver feels: their level at the felt reference.

    ``reference`` is that sensor's location; without one, ``fallback`` says why
    and the causes keep the ranking by evidence. No causes on a no-fault run.
    """

    reference: str | None
    fallback: FeltFallbackValue | None
    causes: list[FeltCauseRow]


@with_config(_FORBID_EXTRA)
class DiagnosisAlternative(TypedDict):
    """The other source the diagnosed order may equally be.

    Without measured RPM an engine order that turns at a wheel or propshaft
    order's rhythm in top gear (where the RPM estimate puts it) cannot be told
    from it; the neutral coast-down or an OBD-II adapter can.
    """

    source: str
    order_code: OrderCodeValue


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
    # Set when the diagnosed order may equally be another source's (an engine
    # order on a road-speed order without measured RPM): the level is then
    # never Strong.
    alternative: NotRequired[DiagnosisAlternative]
    frequency_hz: float | None
    reference_speed_kmh: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    dominant_phase: str | None
    # Share of the moving drive in which the diagnosed order was there (any sensor).
    presence_ratio: float | None
    weak_reasons: list[str]
    # The tapped guided steps the drive's speed shows were done, and those it
    # does not (absent on runs analysed before steps were checked).
    guided_phases: list[GuidedPhaseValue]
    guided_phases_undetected: NotRequired[list[GuidedPhaseValue]]
    speed_dependence: SpeedDependenceValue | None
    order_findings: list[OrderFindingRow]
    amplitude_basis: AmplitudeBasis
    location_amplitudes: list[LocationAmplitudeRow]
    # No cause found, yet a sensor felt a vibration in the elevated strength band
    # (L3) or above: the run must not read as vibration-free.
    unexplained_vibration: bool
    amplitude_vs_speed: list[SpeedAmplitudePoint]
    spectrum: DiagnosisSpectrum | None
    source_checks: list[SourceCheck]
    conditions: TestConditions
    # A driveline-order fault on a car with a known drive layout: the parts to
    # check, the axle the sensors point to first. Empty for an EV (its motor is
    # the driveline order), without a layout, or for another source.
    driveline_parts: NotRequired[list[DrivelinePart]]
    # The causes ranked by what the driver feels (absent on runs analysed before).
    felt: NotRequired[FeltPayload]
