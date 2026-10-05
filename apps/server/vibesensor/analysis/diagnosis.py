"""Run diagnosis block: the verdict, its confidence level, and the evidence the UI/PDF show.

Computed once per run from the analysis result. Amplitudes are reported in mg
at the diagnosed order (from matched-point amplitudes in g) with dB above each
location's own noise floor via the canonical dB helper.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from math import floor, log
from statistics import median
from typing import TYPE_CHECKING, cast

from vibesensor.analysis._reference_resolution import (
    ENGINE_OFF_RPM_SOURCE,
    ESTIMATED_RPM_SOURCE,
    _effective_engine_rpm,
    _tire_reference_from_context,
)
from vibesensor.analysis._sample_metrics import _estimate_strength_floor_amp_g, _sample_top_peaks
from vibesensor.analysis._sensor_locations import _location_label
from vibesensor.analysis.constants import (
    LIGHT_STRENGTH_MAX_DB,
    MIN_ORDER_TRACKING_SLOPE,
    SPEED_COVERAGE_MIN_PCT,
)
from vibesensor.analysis.phase_segmentation import BRAKING_MIN_DURATION_S
from vibesensor.analysis.speed_profile_helpers import run_speed_source, speed_typed_in
from vibesensor.common.units import SECONDS_PER_MINUTE
from vibesensor.domain.car import WEAK_FIELD_CONFIDENCES, ReferenceProvenance, reference_provenance
from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import ConfidenceLevel, DiagnosisVerdict, VibrationSource
from vibesensor.domain.locations import WHEEL_LOCATION_CODES, location_code_for_label
from vibesensor.domain.order_match import (
    OrderMatchObservation,
    frequency_tracking_slope,
    trend_moves,
)
from vibesensor.domain.order_reference import wheel_hz_from_speed_kmh
from vibesensor.dsp.order_bands import ORDER_TOLERANCE_REL
from vibesensor.dsp.strength_bands import BANDS
from vibesensor.dsp.vibration_strength import percentile, vibration_strength_db_scalar
from vibesensor.summary.diagnosis_contracts import (
    AmplitudeBasis,
    DiagnosisPayload,
    DiagnosisSpectrum,
    DriveLayoutValue,
    DrivelinePart,
    FinalDriveAxleValue,
    FuelTypeValue,
    GuidedPhaseValue,
    LocationAmplitudeRow,
    OrderCodeValue,
    OrderFindingRow,
    RpmSourceValue,
    SourceCheck,
    SourceCheckReason,
    SpectrumPeak,
    SpeedAmplitudePoint,
    SpeedDependenceValue,
    TestConditions,
)

if TYPE_CHECKING:
    from vibesensor.analysis._types import Sample
    from vibesensor.domain.test_run import TestRun
    from vibesensor.recording.run_schema import RunGuidedPhase, RunMetadata

__all__ = ["build_diagnosis"]

_G_TO_MG = 1000.0
_SPEED_BIN_KMH = 5.0
_MIN_POINTS_PER_SPEED_BIN = 2
_SPECTRUM_HALF_WINDOW_KMH = 5.0
_SPECTRUM_MIN_WINDOW_SAMPLES = 5
_SPECTRUM_BIN_HZ = 0.5
_SPECTRUM_MAX_HZ = 200.0
_SPECTRUM_MIN_PRESENCE = 0.2
_SPECTRUM_MAX_PEAKS = 40
_INTERMITTENT_PRESENCE = 0.5
_PRESENCE_SLOT_S = 0.5
_PRESENT_LEVEL_RATIO = 0.5
_NARROW_SPEED_KMH = 10.0
_MAX_WEAK_REASONS = 2
_MAX_ORDER_ROWS = 6
# With no cause found, the run still felt a vibration when a sensor's strongest
# peaks (p95) reach the elevated strength band (L3, 26 dB over the floor). The
# p95 of every window's strongest peak sits about 10 dB over the floor on a
# smooth road and in the moderate band (16-26 dB) with a healthy car's residual
# wheel imbalance; a body resonance or an unchecked motor order is well above.
_UNEXPLAINED_MIN_DB = next(band["min_db"] for band in BANDS if band["key"] == "l3")
_MIN_COAST_SAMPLES = 4
# Engine revs take a moment to drop after the shift to neutral, and each
# spectrum still holds the seconds before it: skip the start of the coast-down.
_COAST_SETTLE_S = 3.0
_MIN_PRESENCE_OUTSIDE_COAST = 0.3
_FOLLOWS_ROAD_SPEED_RATIO = 0.6
_FOLLOWS_ENGINE_RATIO = 0.3
_MEASURED_RPM_EXCLUDED = frozenset({"", ESTIMATED_RPM_SOURCE, "missing"})
_ORDER_SOURCES: tuple[VibrationSource, ...] = (
    VibrationSource.WHEEL_TIRE,
    VibrationSource.DRIVELINE,
    VibrationSource.ENGINE,
    VibrationSource.BRAKES,
)
_ALL_WHEELS_MIN_CORNERS = 3
# The engine orders (engine_<m>x) that can sit on a road-speed order in some gear.
_ENGINE_ORDER_MULTIPLES = (1, 2)
_DRIVELINE_ZONE_CODES = frozenset({"driveshaft_tunnel", "transmission"})


def build_diagnosis(
    *,
    test_run: TestRun,
    samples: Sequence[Sample],
    metadata: RunMetadata,
    sensor_count: int,
) -> DiagnosisPayload:
    """Build the persisted diagnosis block for one analysed run."""
    # The top cause names the source and its confidence; the order shown (label,
    # amplitudes, frequency) is that source's dominant order, which workshops act on.
    top_cause = test_run.diagnosis_candidate
    verdict = _verdict(top_cause)
    level = top_cause.confidence_level if top_cause is not None else None
    candidate = None if verdict is DiagnosisVerdict.NO_FAULT else test_run.diagnosis_order_finding
    located = [(sample, _location_label(sample, metadata=metadata)) for sample in samples]
    floors = _location_floors(located)
    braking = _braking_spans(test_run)
    presence = _presence_ratio(candidate, located, braking)
    refs = _references(metadata, samples)
    # A hand-entered speed does not drop while coasting, so the coast-down
    # comparison cannot tell road speed from engine speed; an EV has no engine
    # and no neutral that decouples its motor. Brake judder stops whenever the
    # brakes are off, coasting in neutral included.
    speed_dependence = (
        None
        if refs.manual_speed
        or refs.electric
        or (candidate is not None and candidate.suspected_source is VibrationSource.BRAKES)
        else _speed_dependence(candidate, located, metadata.guided_phases)
    )
    findings = test_run.findings
    # Road-speed orders the engine may have caused: never Strong unless the
    # neutral coast-down kept them going (measured RPM leaves none).
    engine_alike = (
        frozenset()
        if speed_dependence == "vehicle_speed"
        else frozenset(
            finding.finding_id
            for finding in findings
            if _engine_alias_gear(finding, refs) is not None
        )
    )
    alias_gear = _engine_alias_gear(candidate, refs)
    if candidate is not None and alias_gear is not None and speed_dependence == "engine_speed":
        # The neutral coast-down says engine: the road-speed order is the engine's
        # in the gear that puts it there.
        source = candidate.suspected_source
        findings = tuple(
            _in_gear(finding, refs, alias_gear) if finding.suspected_source is source else finding
            for finding in findings
        )
        candidate = _in_gear(candidate, refs, alias_gear)
    rows: list[LocationAmplitudeRow]
    basis: AmplitudeBasis
    if candidate is not None and candidate.matched_points:
        rows = _order_location_amplitudes(candidate, located, floors, braking)
        basis = "order"
    else:
        rows = _overall_location_amplitudes(located, floors)
        basis = "overall"
    zone = _zone(candidate, rows, refs) if candidate is not None else None
    weak_reasons = _weak_reasons(
        candidate,
        presence,
        zone=zone,
        sensor_count=sensor_count,
        manual_speed=refs.manual_speed,
    )
    if _contradicts_coast_test(candidate, speed_dependence):
        verdict = DiagnosisVerdict.WEAK_EVIDENCE
        weak_reasons = ["coast_test_contradicts", *weak_reasons][:_MAX_WEAK_REASONS]
    if candidate is None:
        level = None
    elif verdict is DiagnosisVerdict.WEAK_EVIDENCE:
        level = ConfidenceLevel.WEAK
    elif candidate.finding_id in engine_alike and level is not None:
        level = _at_most_moderate(level)
    location = candidate.strongest_location if candidate is not None else None
    if candidate is not None and candidate.location is not None:
        location = candidate.location.strongest_location or location
    hz_per_kmh = _hz_per_kmh(candidate)
    reference_speed = _reference_speed_kmh(candidate)
    speed_min, speed_max = _matched_speed_range(candidate)
    spectrum_location = _strongest_row_location(rows) or location
    return {
        "verdict": verdict.value,
        "confidence_level": level.value if level is not None else None,
        "finding_id": candidate.finding_id if candidate is not None else None,
        "source": str(candidate.suspected_source) if candidate is not None else None,
        "location": location,
        "zone": zone,
        "order_code": (
            cast(OrderCodeValue, candidate.order_code)
            if candidate is not None and candidate.order_code is not None
            else None
        ),
        "frequency_hz": (
            hz_per_kmh * reference_speed
            if hz_per_kmh is not None and reference_speed is not None
            else _peak_frequency_hz(candidate)
        ),
        "reference_speed_kmh": reference_speed,
        "speed_min_kmh": speed_min,
        "speed_max_kmh": speed_max,
        "dominant_phase": candidate.dominant_phase if candidate is not None else None,
        "presence_ratio": presence,
        "weak_reasons": weak_reasons,
        "guided_phases": _guided_phase_names(metadata.guided_phases),
        "speed_dependence": speed_dependence,
        "order_findings": _order_findings(
            candidate, level, findings, located, braking, engine_alike
        ),
        "amplitude_basis": basis,
        "location_amplitudes": rows,
        "unexplained_vibration": (
            verdict is DiagnosisVerdict.NO_FAULT and basis == "overall" and _elevated(rows)
        ),
        "amplitude_vs_speed": _amplitude_vs_speed(candidate),
        "spectrum": _spectrum(
            located,
            location=spectrum_location,
            centre_speed_kmh=reference_speed,
            refs=refs,
        ),
        "source_checks": _source_checks(
            candidate,
            findings,
            refs,
            speed_dependence,
            braked=_braked(braking),
            engine_alias=alias_gear is not None,
        ),
        "conditions": _conditions(refs),
        "driveline_parts": _driveline_parts(candidate, zone, refs),
    }


def _at_most_moderate(level: ConfidenceLevel) -> ConfidenceLevel:
    return ConfidenceLevel.MODERATE if level is ConfidenceLevel.STRONG else level


def _verdict(candidate: Finding | None) -> DiagnosisVerdict:
    """Fault for a Strong/Moderate candidate, weak evidence for a Weak one, else no fault.

    A Weak candidate that is also faint (below the moderate strength band) is not
    a significant vibration, so the run reads as no fault.
    """
    if candidate is None:
        return DiagnosisVerdict.NO_FAULT
    if candidate.confidence_level is not ConfidenceLevel.WEAK:
        return DiagnosisVerdict.FAULT
    strength = candidate.vibration_strength_db
    if strength is not None and strength < LIGHT_STRENGTH_MAX_DB:
        return DiagnosisVerdict.NO_FAULT
    return DiagnosisVerdict.WEAK_EVIDENCE


@dataclass(frozen=True, slots=True)
class _References:
    """Reference data the order analysis used for this run, and where it came from."""

    tire_circumference_m: float | None
    final_drive_ratio: float | None
    gear_ratio: float | None
    tire_provenance: ReferenceProvenance
    final_drive_provenance: ReferenceProvenance
    gear_ratio_provenance: ReferenceProvenance
    speed_source: str | None
    fuel_type: FuelTypeValue | None
    rpm_source: RpmSourceValue
    # Measured RPM shows the engine running for enough of the drive to test it.
    engine_ran: bool
    drive_layout: DriveLayoutValue | None
    final_drive_axle: FinalDriveAxleValue | None
    # Whether a propshaft drives the rear axle; ``None`` without a drive layout.
    propshaft: bool | None

    @property
    def electric(self) -> bool:
        """A battery-electric car: no engine; the motor turns at the driveshaft order."""
        return self.fuel_type == "EV"

    @property
    def hybrid(self) -> bool:
        """A plug-in hybrid: the engine may be off while it drives electrically."""
        return self.fuel_type == "PHEV"

    @property
    def manual_speed(self) -> bool:
        """The speed was typed in by hand, not measured live (GPS/OBD-II)."""
        return speed_typed_in(self.speed_source)

    @property
    def estimated_final_drive(self) -> bool:
        return self.final_drive_provenance in WEAK_FIELD_CONFIDENCES

    @property
    def estimated_top_gear(self) -> bool:
        return self.gear_ratio_provenance in WEAK_FIELD_CONFIDENCES


def _references(metadata: RunMetadata, samples: Sequence[Sample]) -> _References:
    status = metadata.car.order_reference_status if metadata.car is not None else None
    tire = metadata.tire_circumference_m
    final_drive = _positive(metadata.final_drive_ratio)
    gear = _positive(metadata.current_gear_ratio)
    rpm_source, engine_ran = _rpm_readings(metadata, samples)
    return _References(
        tire_circumference_m=tire,
        final_drive_ratio=final_drive,
        gear_ratio=gear,
        tire_provenance=reference_provenance(
            tire, status.tire_dimensions_confidence if status is not None else None
        ),
        final_drive_provenance=reference_provenance(
            final_drive, status.final_drive_ratio_confidence if status is not None else None
        ),
        gear_ratio_provenance=reference_provenance(
            gear, status.current_gear_ratio_confidence if status is not None else None
        ),
        speed_source=run_speed_source(samples),
        fuel_type=metadata.fuel_type,
        rpm_source=rpm_source,
        engine_ran=engine_ran,
        drive_layout=metadata.drive_layout,
        final_drive_axle=metadata.final_drive_axle,
        propshaft=metadata.propshaft,
    )


def _turns_per_wheel_turn(order_code: str | None, refs: _References) -> float | None:
    """How often a wheel or propshaft order repeats per wheel turn."""
    final_drive = refs.final_drive_ratio
    if order_code in ("T1", "T2"):
        return float(order_code[1])
    if order_code in ("P1", "P2") and final_drive is not None:
        return float(order_code[1]) * final_drive
    return None


def _engine_alias_gear(candidate: Finding | None, refs: _References) -> float | None:
    """The gear ratio in which an engine order sits on the candidate's road-speed order.

    RPM estimated from speed assumes top gear, but the drive may have been in
    any gear: in gear ``g`` the engine's ``m``-th order repeats ``m * g * final
    drive`` times per wheel turn. When that equals the candidate's wheel or
    propshaft order for a ratio at or above the top gear's (a lower gear has a
    higher ratio), only measured RPM or a neutral coast-down tells them apart.
    Of the engine orders that fit, the gear closest to direct drive (1:1) is
    returned; ``None`` when no gear puts an engine order there.
    """
    if candidate is None or refs.rpm_source != "estimated_top_gear" or refs.electric:
        return None
    turns = _turns_per_wheel_turn(candidate.order_code, refs)
    final_drive, top_gear = refs.final_drive_ratio, refs.gear_ratio
    if turns is None or final_drive is None or top_gear is None:
        return None
    gears = [
        gear
        for multiple in _ENGINE_ORDER_MULTIPLES
        if (gear := turns / (multiple * final_drive)) >= top_gear * (1.0 - ORDER_TOLERANCE_REL)
    ]
    return min(gears, key=lambda gear: abs(log(gear)), default=None)


def _in_gear(finding: Finding, refs: _References, gear: float) -> Finding:
    """*finding* as the engine order it is in *gear*, or unchanged when it is none."""
    turns = _turns_per_wheel_turn(finding.order_code, refs)
    if turns is None or refs.final_drive_ratio is None:
        return finding
    multiple = turns / (refs.final_drive_ratio * gear)
    for engine_multiple in _ENGINE_ORDER_MULTIPLES:
        if abs(multiple - engine_multiple) <= engine_multiple * ORDER_TOLERANCE_REL:
            return replace(
                finding,
                suspected_source=VibrationSource.ENGINE,
                finding_key=f"engine_{engine_multiple}x",
            )
    return finding


def _positive(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None


# -- amplitudes ---------------------------------------------------------------


def _mg(amp_g: float) -> float:
    return amp_g * _G_TO_MG


def _location_floors(located: Iterable[tuple[Sample, str]]) -> dict[str, float]:
    floors: dict[str, list[float]] = defaultdict(list)
    for sample, location in located:
        floor_amp = _estimate_strength_floor_amp_g(sample)
        if floor_amp is not None:
            floors[location].append(floor_amp)
    return {location: median(values) for location, values in floors.items() if values}


def _with_ratios(
    amplitudes: dict[str, float | None],
    *,
    floors: dict[str, float],
    presence: dict[str, float | None],
) -> list[LocationAmplitudeRow]:
    strongest = max((amp for amp in amplitudes.values() if amp is not None), default=None)
    rows: list[LocationAmplitudeRow] = []
    for location, amp in amplitudes.items():
        floor_amp = floors.get(location)
        rows.append(
            {
                "location": location,
                "amplitude_mg": _mg(amp) if amp is not None else None,
                "db_above_floor": (
                    vibration_strength_db_scalar(peak_band_rms_amp_g=amp, floor_amp_g=floor_amp)
                    if amp is not None and floor_amp is not None
                    else None
                ),
                "ratio_to_strongest": (amp / strongest if amp is not None and strongest else None),
                "presence_ratio": presence.get(location),
            }
        )
    rows.sort(key=lambda row: -(row["amplitude_mg"] or -1.0))
    return rows


def _order_location_amplitudes(
    candidate: Finding,
    located: Sequence[tuple[Sample, str]],
    floors: dict[str, float],
    braking: Sequence[tuple[float, float]],
) -> list[LocationAmplitudeRow]:
    amps: dict[str, list[float]] = defaultdict(list)
    heard: Counter[str] = Counter()
    for point in candidate.matched_points:
        if point.amp > 0 and point.location:
            amps[point.location].append(point.amp)
            heard[point.location] += point.heard
    brakes = candidate.suspected_source is VibrationSource.BRAKES
    speed_samples: Counter[str] = Counter(
        location
        for sample, location in located
        if sample.speed_kmh is not None
        and sample.speed_kmh > 0
        and (not brakes or _in_spans(sample.t_s, braking))
    )
    locations = sorted({location for _sample, location in located} | set(amps))
    medians: dict[str, float | None] = {
        location: median(amps[location]) if amps.get(location) else None for location in locations
    }
    presence: dict[str, float | None] = {
        location: (
            min(1.0, heard[location] / speed_samples[location]) if speed_samples[location] else None
        )
        for location in locations
    }
    return _with_ratios(medians, floors=floors, presence=presence)


def _overall_location_amplitudes(
    located: Sequence[tuple[Sample, str]],
    floors: dict[str, float],
) -> list[LocationAmplitudeRow]:
    peaks: dict[str, list[float]] = defaultdict(list)
    for sample, location in located:
        amp = sample.strength_peak_amp_g
        if amp is not None and amp > 0:
            peaks[location].append(amp)
    locations = sorted({location for _sample, location in located})
    p95: dict[str, float | None] = {
        location: percentile(sorted(peaks[location]), 0.95) if peaks.get(location) else None
        for location in locations
    }
    return _with_ratios(p95, floors=floors, presence=dict.fromkeys(locations))


def _elevated(rows: Sequence[LocationAmplitudeRow]) -> bool:
    """A sensor's strongest peaks reached the elevated strength band (L3) or above."""
    return any(
        row["db_above_floor"] is not None and row["db_above_floor"] >= _UNEXPLAINED_MIN_DB
        for row in rows
    )


def _strongest_row_location(rows: Sequence[LocationAmplitudeRow]) -> str | None:
    return rows[0]["location"] if rows and rows[0]["amplitude_mg"] is not None else None


def _amplitude_vs_speed(candidate: Finding | None) -> list[SpeedAmplitudePoint]:
    if candidate is None:
        return []
    bins: dict[tuple[str, float], list[float]] = defaultdict(list)
    for point in candidate.matched_points:
        speed = point.speed_kmh
        if speed is None or speed <= 0 or point.amp <= 0 or not point.location:
            continue
        centre = floor(speed / _SPEED_BIN_KMH) * _SPEED_BIN_KMH + _SPEED_BIN_KMH / 2
        bins[(point.location, centre)].append(point.amp)
    return [
        {"speed_kmh": centre, "location": location, "amplitude_mg": _mg(median(amps))}
        for (location, centre), amps in sorted(bins.items(), key=lambda item: item[0])
        if len(amps) >= _MIN_POINTS_PER_SPEED_BIN
    ]


# -- frequency / speed --------------------------------------------------------


def _hz_per_kmh(candidate: Finding | None) -> float | None:
    if candidate is None:
        return None
    ratios = [
        point.matched_hz / point.speed_kmh
        for point in candidate.matched_points
        if point.speed_kmh is not None and point.speed_kmh > 0 and point.matched_hz > 0
    ]
    return median(ratios) if ratios else None


def _speed_band_bounds(band: str | None) -> tuple[float, float] | None:
    if not band:
        return None
    bounds = band.split(" ", 1)[0].split("-", 1)
    try:
        return float(bounds[0]), float(bounds[1])
    except (IndexError, ValueError):
        return None


def _reference_speed_kmh(candidate: Finding | None) -> float | None:
    """Median matched speed inside the finding's strongest speed band (else overall)."""
    if candidate is None:
        return None
    speeds = [
        point.speed_kmh
        for point in candidate.matched_points
        if point.speed_kmh is not None and point.speed_kmh > 0
    ]
    bounds = _speed_band_bounds(candidate.strongest_speed_band)
    if bounds is not None:
        in_band = [speed for speed in speeds if bounds[0] <= speed < bounds[1]]
        if in_band:
            return median(in_band)
        if not speeds:
            return (bounds[0] + bounds[1]) / 2
    return median(speeds) if speeds else None


def _matched_speed_range(candidate: Finding | None) -> tuple[float | None, float | None]:
    if candidate is None:
        return None, None
    speeds = sorted(
        point.speed_kmh
        for point in _heard_points(candidate)
        if point.speed_kmh is not None and point.speed_kmh > 0
    )
    if not speeds:
        return None, None
    return percentile(speeds, 0.05), percentile(speeds, 0.95)


def _heard_points(finding: Finding) -> Sequence[OrderMatchObservation]:
    """The finding's heard matches; all of them when none is heard."""
    return [point for point in finding.matched_points if point.heard] or finding.matched_points


def _peak_frequency_hz(candidate: Finding | None) -> float | None:
    if candidate is None:
        return None
    if candidate.frequency_hz is not None:
        return candidate.frequency_hz
    head = candidate.order.split(" ", 1)[0]
    try:
        return float(head) if candidate.order.endswith("Hz") else None
    except ValueError:
        return None


def _braking_spans(test_run: TestRun) -> list[tuple[float, float]]:
    """The time spans ``(start_t_s, end_t_s)`` the car spent on the brakes."""
    return [
        (segment.start_t_s, segment.end_t_s)
        for segment in test_run.driving_segments
        if segment.phase is DrivingPhase.BRAKING
        and segment.start_t_s is not None
        and segment.end_t_s is not None
    ]


def _in_spans(t_s: float | None, spans: Sequence[tuple[float, float]]) -> bool:
    return t_s is not None and any(start <= t_s <= end for start, end in spans)


def _braked(braking: Sequence[tuple[float, float]]) -> bool:
    """The drive braked firmly from speed for long enough to show brake judder."""
    return sum(end - start for start, end in braking) >= BRAKING_MIN_DURATION_S


def _presence_ratio(
    candidate: Finding | None,
    located: Sequence[tuple[Sample, str]],
    braking: Sequence[tuple[float, float]] = (),
) -> float | None:
    """Share of the moving drive in which the order was there, at a sensor that hears it.

    Counted over the whole drive in short time slots; brake judder over the
    time spent braking, the only time it can be there. The finding's match rate
    (rescued to its best location or speed band) does not say this, and each
    spectrum spans a few seconds, so it still shows a vibration that stopped
    seconds ago. A heard match counts when it reaches half the order's usual
    level there at that speed, i.e. the vibration filled most of that spectrum.
    """
    if candidate is None or candidate.evidence is None:
        return None
    if not candidate.matched_points:
        return candidate.evidence.presence_ratio
    brakes = candidate.suspected_source is VibrationSource.BRAKES
    moving = {
        floor(sample.t_s / _PRESENCE_SLOT_S)
        for sample, _location in located
        if sample.t_s is not None
        and sample.speed_kmh is not None
        and sample.speed_kmh > 0
        and (not brakes or _in_spans(sample.t_s, braking))
    }
    if not moving:
        return candidate.evidence.match_rate
    heard: dict[tuple[str, float], list[tuple[float, float]]] = defaultdict(list)
    for point in candidate.matched_points:
        location = point.location or ""
        if point.t_s is None or point.speed_kmh is None or point.speed_kmh <= 0:
            continue
        if not point.heard:
            continue
        speed_bin = floor(point.speed_kmh / _SPEED_BIN_KMH)
        heard[(location, speed_bin)].append((point.t_s, point.amp))
    present: set[int] = set()
    for points in heard.values():
        usual = median(amp for _t_s, amp in points)
        present.update(
            floor(t_s / _PRESENCE_SLOT_S)
            for t_s, amp in points
            if amp >= _PRESENT_LEVEL_RATIO * usual
        )
    return len(present & moving) / len(moving)


def _is_candidate(finding: Finding, candidate: Finding | None) -> bool:
    return candidate is not None and finding.finding_id == candidate.finding_id


def _order_findings(
    candidate: Finding | None,
    level: ConfidenceLevel | None,
    findings: Sequence[Finding],
    located: Sequence[tuple[Sample, str]],
    braking: Sequence[tuple[float, float]],
    engine_alike: frozenset[str] = frozenset(),
) -> list[OrderFindingRow]:
    """Surfaced order-tracked findings, one per order, the diagnosed one first at its level.

    Orders are listed from Moderate up; a repeated order keeps its best-ranked
    finding. The diagnosed source's other order is listed once even when weak on
    its own: a mechanic reads T1 with T2 present differently from T1 alone. An
    order the engine may have caused in some gear (*engine_alike*) is never
    listed as Strong.
    """
    surfaced = [
        finding for finding in findings if finding.order_code is not None and finding.should_surface
    ]
    tracked = [
        finding
        for finding in surfaced
        if _is_candidate(finding, candidate) or finding.confidence_level is not ConfidenceLevel.WEAK
    ]
    if candidate is not None:
        listed = {
            finding.order_code
            for finding in tracked
            if finding.suspected_source is candidate.suspected_source
        }
        for finding in surfaced:
            if (
                finding.suspected_source is candidate.suspected_source
                and finding.order_code not in listed
            ):
                listed.add(finding.order_code)
                tracked.append(finding)
    tracked.sort(key=lambda finding: not _is_candidate(finding, candidate))
    # One row per order: the same order found again at another corner or speed
    # band belongs in the per-location amplitudes, not in a second worksheet row.
    per_order: dict[str, Finding] = {}
    for finding in tracked:
        per_order.setdefault(cast(str, finding.order_code), finding)
    rows: list[OrderFindingRow] = []
    for finding in list(per_order.values())[:_MAX_ORDER_ROWS]:
        diagnosed = _is_candidate(finding, candidate)
        hz_per_kmh = _hz_per_kmh(finding)
        reference_speed = _reference_speed_kmh(finding)
        speed_min, speed_max = _matched_speed_range(finding)
        location = finding.location.strongest_location if finding.location else None
        rows.append(
            {
                "finding_id": finding.finding_id,
                "source": str(finding.suspected_source),
                "order_code": cast(OrderCodeValue, finding.order_code),
                "location": location or finding.strongest_location,
                "frequency_hz": (
                    hz_per_kmh * reference_speed
                    if hz_per_kmh is not None and reference_speed is not None
                    else None
                ),
                "reference_speed_kmh": reference_speed,
                "speed_min_kmh": speed_min,
                "speed_max_kmh": speed_max,
                "phases": list(finding.phases_detected),
                "presence_ratio": _presence_ratio(finding, located, braking),
                "confidence_level": (
                    level
                    if diagnosed and level is not None
                    else (
                        _at_most_moderate(finding.confidence_level)
                        if finding.finding_id in engine_alike
                        else finding.confidence_level
                    )
                ).value,
            }
        )
    return rows


# -- interpretation -----------------------------------------------------------


def _axle_zone(codes: Iterable[str]) -> str | None:
    axles = {code.split("_", 1)[0] for code in codes if code in WHEEL_LOCATION_CODES}
    return f"{axles.pop()}_axle" if len(axles) == 1 else None


def _zone(
    candidate: Finding, rows: Sequence[LocationAmplitudeRow], refs: _References
) -> str | None:
    """Map the diagnosed source and its evidence to a corner or a car zone."""
    source = candidate.suspected_source
    if source is VibrationSource.ENGINE:
        return "engine_bay"
    top_codes = [
        code
        for row in rows
        if row["amplitude_mg"] is not None
        and (row["ratio_to_strongest"] or 0.0) >= 1 / 1.5
        and (code := location_code_for_label(row["location"])) is not None
    ]
    if source is VibrationSource.BRAKES:
        # Judder comes from an axle's brake discs, felt through the steering
        # (front) or the seat and pedal (rear): the axle the wheel sensors near
        # the top share, else the strongest wheel sensor's axle.
        wheels = [code for code in top_codes if code in WHEEL_LOCATION_CODES]
        return _axle_zone(wheels) or (_axle_zone(wheels[:1]) if wheels else None)
    if source is VibrationSource.DRIVELINE:
        if top_codes and top_codes[0] in _DRIVELINE_ZONE_CODES:
            return top_codes[0]
        return _axle_zone(top_codes) or _no_propshaft_axle_zone(refs) or "driveshaft_tunnel"
    if source is VibrationSource.WHEEL_TIRE and not candidate.weak_spatial_separation:
        # A clearly dominant corner names the zone, as it names the location:
        # the per-location medians over the whole drive dilute a fault that was
        # only there for part of it.
        location = (
            candidate.location.strongest_location if candidate.location is not None else None
        ) or candidate.strongest_location
        code = location_code_for_label(location) if location else None
        if code in WHEEL_LOCATION_CODES:
            return code
    if not top_codes:
        return None
    if len(top_codes) > 1 and source is VibrationSource.WHEEL_TIRE:
        wheels = [code for code in top_codes if code in WHEEL_LOCATION_CODES]
        if len(wheels) >= _ALL_WHEELS_MIN_CORNERS:
            return "all_wheels"
        if len(wheels) == 1:
            # The only wheel sensor near the top names its corner, not its axle.
            return wheels[0]
        return _axle_zone(wheels) or top_codes[0]
    return top_codes[0]


def _weak_reasons(
    candidate: Finding | None,
    presence: float | None,
    *,
    zone: str | None,
    sensor_count: int,
    manual_speed: bool,
) -> list[str]:
    if candidate is None:
        return []
    # A hand-entered speed comes first: the order match holds only at that speed.
    reasons: list[str] = ["manual_speed"] if manual_speed else []
    source = candidate.suspected_source
    if source is VibrationSource.BRAKES:
        # Brake judder names an axle: spread over its two wheels is expected.
        if zone is None:
            reasons.append("spread_across_locations")
    elif (
        source not in (VibrationSource.ENGINE, VibrationSource.DRIVELINE)
        and candidate.weak_spatial_separation
    ):
        reasons.append("spread_across_locations")
    speed_min, speed_max = _matched_speed_range(candidate)
    if (
        speed_min is not None
        and speed_max is not None
        and speed_max - speed_min < _NARROW_SPEED_KMH
    ):
        reasons.append("narrow_speed_range")
    if presence is not None and presence < _INTERMITTENT_PRESENCE:
        reasons.append("intermittent")
    strength = candidate.vibration_strength_db
    if strength is not None and strength < LIGHT_STRENGTH_MAX_DB:
        reasons.append("faint")
    if sensor_count < 2:
        reasons.append("single_sensor")
    return reasons[:_MAX_WEAK_REASONS]


def _source_checks(
    candidate: Finding | None,
    findings: Sequence[Finding],
    refs: _References,
    speed_dependence: SpeedDependenceValue | None,
    *,
    braked: bool,
    engine_alias: bool = False,
) -> list[SourceCheck]:
    rpm_source = refs.rpm_source
    seen = {
        finding.suspected_source
        for finding in findings
        if finding.order_code is not None
        and finding.should_surface
        and finding.confidence_level is not ConfidenceLevel.WEAK
    }
    if candidate is not None:
        seen.add(candidate.suspected_source)
    checks: list[SourceCheck] = []
    for source in _ORDER_SOURCES:
        if source is VibrationSource.ENGINE and refs.electric:
            checks.append(
                {"source": str(source), "status": "not_applicable", "reason": "electric_car"}
            )
            continue
        # The neutral coast-down excludes a source whatever its order match says,
        # and without needing its order reference.
        coast_reason = _coast_ruled_out_reason(source, speed_dependence)
        if coast_reason is not None and (
            candidate is None or source is not candidate.suspected_source
        ):
            checks.append({"source": str(source), "status": "ruled_out", "reason": coast_reason})
            continue
        if source in seen:
            checks.append({"source": str(source), "status": "candidate", "reason": None})
            continue
        if source is VibrationSource.ENGINE and engine_alias:
            # In some gear the engine turns at the diagnosed order's rhythm.
            checks.append(
                {
                    "source": str(source),
                    "status": "not_testable",
                    "reason": "same_rhythm_as_candidate",
                }
            )
            continue
        if source is VibrationSource.BRAKES:
            checks.append(_brakes_check(refs, braked=braked))
            continue
        if (
            source is VibrationSource.WHEEL_TIRE
            and candidate is not None
            and candidate.suspected_source is VibrationSource.BRAKES
        ):
            # The wheel order was there, but only while braking: not a wheel or tire.
            checks.append(
                {"source": str(source), "status": "ruled_out", "reason": "only_while_braking"}
            )
            continue
        # Measured RPM places the engine orders without the speed, tire or drive ratios.
        measured_engine = source is VibrationSource.ENGINE and rpm_source == "measured"
        reason: SourceCheckReason | None
        if measured_engine:
            # Measured RPM also shows when the engine ran; with it off for most of
            # the drive (a hybrid driving electrically) its orders were not tested.
            reason = None if refs.engine_ran else "engine_not_running"
        elif refs.tire_circumference_m is None:
            reason = "no_tire_reference"
        elif source is not VibrationSource.WHEEL_TIRE and refs.final_drive_ratio is None:
            reason = "no_drive_reference"
        elif source is VibrationSource.ENGINE and rpm_source == "none":
            reason = "no_engine_reference"
        elif refs.manual_speed:
            # Every order was placed at the typed-in speed: no match proves nothing
            # unless the car really held exactly that speed.
            reason = "manual_speed"
        else:
            reason = None
        if reason is not None:
            checks.append({"source": str(source), "status": "not_testable", "reason": reason})
            continue
        estimate = None if measured_engine else _estimate_reason(source, refs)
        checks.append(
            {
                "source": str(source),
                "status": "ruled_out" if estimate is None else "ruled_out_estimated",
                "reason": estimate or "no_matching_order",
            }
        )
    return checks


def _brakes_check(refs: _References, *, braked: bool) -> SourceCheck:
    """Brake judder is a wheel order while braking: it needs the tire size and real braking."""
    reason: SourceCheckReason | None
    if refs.tire_circumference_m is None:
        reason = "no_tire_reference"
    elif refs.manual_speed:
        # A typed-in speed never drops, so braking cannot be seen.
        reason = "manual_speed"
    elif not braked:
        # Coasting is not braking: judder shows only with the brakes on.
        reason = "no_braking"
    else:
        return {
            "source": str(VibrationSource.BRAKES),
            "status": "ruled_out",
            "reason": "no_matching_order",
        }
    return {"source": str(VibrationSource.BRAKES), "status": "not_testable", "reason": reason}


def _estimate_reason(source: VibrationSource, refs: _References) -> SourceCheckReason | None:
    """Why a no-match for *source* rests on an estimate, or ``None`` when it does not.

    Weak library ratios hedge the driveline and the engine; engine RPM estimated
    from speed always assumes top gear, and a plug-in hybrid's engine may have
    been off while it drove electrically.
    """
    if source is VibrationSource.WHEEL_TIRE:
        return None
    if source is VibrationSource.ENGINE and refs.hybrid:
        return "engine_may_be_off"
    if refs.estimated_final_drive:
        return "estimated_final_drive"
    if source is VibrationSource.DRIVELINE:
        return None
    if refs.estimated_top_gear:
        return "estimated_top_gear"
    return "top_gear_assumed"


def _coast_ruled_out_reason(
    source: VibrationSource,
    speed_dependence: SpeedDependenceValue | None,
) -> SourceCheckReason | None:
    if speed_dependence == "vehicle_speed" and source is VibrationSource.ENGINE:
        return "stayed_in_neutral"
    if speed_dependence == "engine_speed" and source is not VibrationSource.ENGINE:
        return "stopped_in_neutral"
    return None


# -- guided test drive --------------------------------------------------------


def _guided_phase_names(phases: Sequence[RunGuidedPhase]) -> list[GuidedPhaseValue]:
    names: list[GuidedPhaseValue] = []
    for phase in phases:
        if phase.phase not in names:
            names.append(phase.phase)
    return names


def _speed_dependence(
    candidate: Finding | None,
    located: Sequence[tuple[Sample, str]],
    phases: Sequence[RunGuidedPhase],
) -> SpeedDependenceValue | None:
    """Whether the diagnosed order kept going while coasting in neutral (guided test).

    In neutral the engine drops to idle while road speed carries on, so a
    wheel or driveline order stays present and an engine order disappears.
    Compares the order's presence at its strongest location inside the guided
    coast-down window (after it settles) with its presence during the rest of
    the run. Only heard matches count: once an engine order is gone, road
    noise still lands near its predicted path from time to time.
    """
    if candidate is None or not candidate.matched_points:
        return None
    windows = [
        (phase.start_t_s, phase.end_t_s if phase.end_t_s is not None else float("inf"))
        for phase in phases
        if phase.phase == "coast_down"
    ]
    settled = [(start + _COAST_SETTLE_S, end) for start, end in windows]
    if not windows:
        return None
    by_location = Counter(point.location for point in candidate.matched_points if point.heard)
    if not by_location:
        return None
    location = by_location.most_common(1)[0][0]

    def in_window(t_s: float, spans: Sequence[tuple[float, float]]) -> bool:
        return any(start <= t_s < end for start, end in spans)

    def split(times: Sequence[float]) -> tuple[int, int]:
        """Count *times* inside the settled coast-down and outside any coast-down."""
        inside = sum(1 for t_s in times if in_window(t_s, settled))
        outside = sum(1 for t_s in times if not in_window(t_s, windows))
        return inside, outside

    inside, outside = split(
        [
            sample.t_s
            for sample, label in located
            if label == location
            and sample.t_s is not None
            and sample.speed_kmh is not None
            and sample.speed_kmh > 0
        ]
    )
    if inside < _MIN_COAST_SAMPLES or outside < _MIN_COAST_SAMPLES:
        return None
    timed = [
        (point.t_s, point)
        for point in candidate.matched_points
        if point.location == location and point.t_s is not None and point.heard
    ]
    matched_inside, matched_outside = split([t_s for t_s, _point in timed])
    coast_points = [point for t_s, point in timed if in_window(t_s, settled)]
    coast_speeds = [
        (sample.t_s, sample.speed_kmh)
        for sample, label in located
        if label == location
        and sample.t_s is not None
        and sample.speed_kmh is not None
        and in_window(sample.t_s, settled)
    ]
    slope = frequency_tracking_slope(coast_points) if trend_moves(coast_speeds) else None
    if slope is not None and slope < MIN_ORDER_TRACKING_SLOPE:
        # A fixed tone near the order's path while coasting, not the order.
        matched_inside = 0
    present_inside = matched_inside / inside
    present_outside = matched_outside / outside
    if present_outside < _MIN_PRESENCE_OUTSIDE_COAST:
        return None
    ratio = present_inside / present_outside
    if ratio >= _FOLLOWS_ROAD_SPEED_RATIO:
        return "vehicle_speed"
    if ratio <= _FOLLOWS_ENGINE_RATIO:
        return "engine_speed"
    return None


def _contradicts_coast_test(
    candidate: Finding | None,
    speed_dependence: SpeedDependenceValue | None,
) -> bool:
    if candidate is None or speed_dependence is None:
        return False
    is_engine = candidate.suspected_source is VibrationSource.ENGINE
    road_source = candidate.suspected_source in (
        VibrationSource.WHEEL_TIRE,
        VibrationSource.DRIVELINE,
    )
    return (is_engine and speed_dependence == "vehicle_speed") or (
        road_source and speed_dependence == "engine_speed"
    )


def _rpm_readings(metadata: RunMetadata, samples: Sequence[Sample]) -> tuple[RpmSourceValue, bool]:
    """Where the engine RPM the analysis used came from, and whether the engine ran.

    Per sample as the order analysis resolves it (``_effective_engine_rpm``): a
    plug-in hybrid's measured 0 rpm (engine off) counts as measured RPM; a
    combustion car's 0 rpm reading is a bad one, estimated from speed instead.
    """
    tire_circumference_m, _ = _tire_reference_from_context(metadata)
    measured = estimated = running = 0
    for sample in samples:
        rpm, source = _effective_engine_rpm(sample, metadata, tire_circumference_m)
        if source == ENGINE_OFF_RPM_SOURCE:
            measured += 1
        elif rpm is None or rpm <= 0:
            continue
        elif source.strip().lower() in _MEASURED_RPM_EXCLUDED:
            estimated += 1
        else:
            measured += 1
            running += 1
    engine_ran = bool(measured) and 100.0 * running / measured >= SPEED_COVERAGE_MIN_PCT
    if measured and measured >= estimated:
        return "measured", engine_ran
    return ("estimated_top_gear" if estimated else "none"), engine_ran


def _no_propshaft_axle_zone(refs: _References) -> str | None:
    """Where a driveline order no axle dominates comes from on a car without a propshaft.

    On an engined car without a propshaft (front-wheel drive, or an e-AWD hybrid)
    the order is the final drive's, on its axle; there is no tunnel shaft to blame.
    An EV's motor order keeps the tunnel (its drive unit).
    """
    if refs.electric or refs.propshaft is not False or refs.final_drive_axle is None:
        return None
    return f"{refs.final_drive_axle}_axle"


def _driveline_parts(
    candidate: Finding | None, zone: str | None, refs: _References
) -> list[DrivelinePart]:
    """The driveline parts a driveline-order fault points to, the likelier first.

    Without a propshaft only the front axle's drive turns at the order; a
    rear-wheel-drive car's is the propshaft and rear axle. An all-wheel-drive car
    has both: the axle the sensors point to comes first. An EV's motor is the
    driveline order, and without a layout the parts are not known.
    """
    if (
        candidate is None
        or candidate.suspected_source is not VibrationSource.DRIVELINE
        or refs.electric
        or refs.propshaft is None
    ):
        return []
    if refs.propshaft is False:
        return ["front_drive"]
    if refs.drive_layout == "RWD":
        return ["propshaft_rear"]
    if zone == "front_axle":
        return ["front_drive", "propshaft_rear"]
    return ["propshaft_rear", "front_drive"]


def _conditions(refs: _References) -> TestConditions:
    return {
        "speed_source": refs.speed_source,
        "rpm_source": refs.rpm_source,
        "tire_circumference_m": refs.tire_circumference_m,
        "final_drive_ratio": refs.final_drive_ratio,
        "gear_ratio": refs.gear_ratio,
        "tire_provenance": refs.tire_provenance,
        "final_drive_provenance": refs.final_drive_provenance,
        "gear_ratio_provenance": refs.gear_ratio_provenance,
        "fuel_type": refs.fuel_type,
        "drive_layout": refs.drive_layout,
        "final_drive_axle": refs.final_drive_axle,
        "propshaft": refs.propshaft,
    }


# -- spectrum -----------------------------------------------------------------


def _measured_rpm(samples: Sequence[Sample]) -> float | None:
    rpms = [
        sample.engine_rpm
        for sample in samples
        if sample.engine_rpm is not None
        and sample.engine_rpm > 0
        and sample.engine_rpm_source.strip().lower() not in _MEASURED_RPM_EXCLUDED
    ]
    return median(rpms) if rpms else None


def _order_markers(
    refs: _References, speed_kmh: float, measured_rpm: float | None
) -> dict[str, float]:
    """Order frequencies at *speed_kmh*; measured RPM places E1/E2, as in the analysis."""
    tire = refs.tire_circumference_m
    wheel = wheel_hz_from_speed_kmh(speed_kmh, tire) if tire is not None else None
    markers: dict[str, float] = {}
    engine = measured_rpm / SECONDS_PER_MINUTE if measured_rpm is not None else None
    if wheel is not None:
        markers |= {"T1": wheel, "T2": 2 * wheel}
        if refs.final_drive_ratio is not None:
            shaft = wheel * refs.final_drive_ratio
            markers |= {"P1": shaft, "P2": 2 * shaft}
            if engine is None and refs.gear_ratio is not None:
                engine = shaft * refs.gear_ratio
    # An EV's motor is the driveshaft order (P1/P2); it has no engine orders.
    if engine is not None and not refs.electric:
        markers |= {"E1": engine, "E2": 2 * engine}
    return markers


def _spectrum(
    located: Sequence[tuple[Sample, str]],
    *,
    location: str | None,
    centre_speed_kmh: float | None,
    refs: _References,
) -> DiagnosisSpectrum | None:
    if location is None:
        return None
    # Moving samples only: standing still is no point on the speed axis.
    moving = [
        (sample, sample.speed_kmh)
        for sample, label in located
        if label == location and sample.speed_kmh is not None and sample.speed_kmh > 0
    ]
    if not moving:
        return None
    centre = (
        centre_speed_kmh
        if centre_speed_kmh is not None
        else median(speed for _sample, speed in moving)
    )
    in_window = [
        (sample, speed)
        for sample, speed in moving
        if abs(speed - centre) <= _SPECTRUM_HALF_WINDOW_KMH
    ]
    if len(in_window) < _SPECTRUM_MIN_WINDOW_SAMPLES:
        in_window = moving
    window = [sample for sample, _speed in in_window]
    window_speeds = [speed for _sample, speed in in_window]
    bins: dict[float, list[float]] = defaultdict(list)
    for sample in window:
        seen: dict[float, float] = {}
        for hz, amp in _sample_top_peaks(sample):
            if hz > _SPECTRUM_MAX_HZ:
                continue
            key = floor(hz / _SPECTRUM_BIN_HZ) * _SPECTRUM_BIN_HZ + _SPECTRUM_BIN_HZ / 2
            seen[key] = max(amp, seen.get(key, 0.0))
        for key, amp in seen.items():
            bins[key].append(amp)
    min_count = max(1, int(len(window) * _SPECTRUM_MIN_PRESENCE))
    recurring = [(hz, median(amps)) for hz, amps in bins.items() if len(amps) >= min_count]
    recurring.sort(key=lambda item: -item[1])
    peaks: list[SpectrumPeak] = [
        {"hz": hz, "amplitude_mg": _mg(amp)} for hz, amp in sorted(recurring[:_SPECTRUM_MAX_PEAKS])
    ]
    floors = [
        floor_amp
        for sample in window
        if (floor_amp := _estimate_strength_floor_amp_g(sample)) is not None
    ]
    window_centre = median(window_speeds)
    return {
        "location": location,
        "speed_min_kmh": min(window_speeds),
        "speed_max_kmh": max(window_speeds),
        "floor_mg": _mg(median(floors)) if floors else None,
        "peaks": peaks,
        "order_markers": _order_markers(refs, window_centre, _measured_rpm(window)),
    }
