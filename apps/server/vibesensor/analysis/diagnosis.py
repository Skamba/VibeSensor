"""Run diagnosis block: the verdict, its confidence level, and the evidence the UI/PDF show.

Computed once per run from the analysis result. Amplitudes are reported in mg
at the diagnosed order (from matched-point amplitudes in g) with dB above each
location's own noise floor via the canonical dB helper.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import floor
from statistics import median
from typing import TYPE_CHECKING, cast

from vibesensor.analysis._sample_metrics import _estimate_strength_floor_amp_g, _sample_top_peaks
from vibesensor.analysis._sensor_locations import _location_label
from vibesensor.analysis.constants import LIGHT_STRENGTH_MAX_DB, MIN_ORDER_TRACKING_SLOPE
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import ConfidenceLevel, DiagnosisVerdict, VibrationSource
from vibesensor.domain.locations import WHEEL_LOCATION_CODES, location_code_for_label
from vibesensor.domain.order_match import frequency_tracking_slope, trend_moves
from vibesensor.domain.order_reference import wheel_hz_from_speed_kmh
from vibesensor.dsp.vibration_strength import percentile, vibration_strength_db_scalar
from vibesensor.summary.diagnosis_contracts import (
    AmplitudeBasis,
    DiagnosisPayload,
    DiagnosisSpectrum,
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
_NARROW_SPEED_KMH = 10.0
_MAX_WEAK_REASONS = 2
_MAX_ORDER_ROWS = 6
_MIN_COAST_SAMPLES = 4
# Engine revs take a moment to drop after the shift to neutral, and each
# spectrum still holds the seconds before it: skip the start of the coast-down.
_COAST_SETTLE_S = 3.0
_MIN_PRESENCE_OUTSIDE_COAST = 0.3
_FOLLOWS_ROAD_SPEED_RATIO = 0.6
_FOLLOWS_ENGINE_RATIO = 0.3
_MEASURED_RPM_EXCLUDED = frozenset({"", "estimated_from_speed_and_ratios", "missing"})
_ORDER_SOURCES: tuple[VibrationSource, ...] = (
    VibrationSource.WHEEL_TIRE,
    VibrationSource.DRIVELINE,
    VibrationSource.ENGINE,
)
_ALL_WHEELS_MIN_CORNERS = 3
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
    speed_dependence = _speed_dependence(candidate, located, metadata.guided_phases)
    weak_reasons = _weak_reasons(candidate, sensor_count=sensor_count)
    if _contradicts_coast_test(candidate, speed_dependence):
        verdict = DiagnosisVerdict.WEAK_EVIDENCE
        weak_reasons = ["coast_test_contradicts", *weak_reasons][:_MAX_WEAK_REASONS]
    refs = _References(
        tire_circumference_m=metadata.tire_circumference_m,
        final_drive_ratio=_positive(metadata.final_drive_ratio),
        gear_ratio=_positive(metadata.current_gear_ratio),
    )
    rows: list[LocationAmplitudeRow]
    basis: AmplitudeBasis
    if candidate is not None and candidate.matched_points:
        rows = _order_location_amplitudes(candidate, located)
        basis = "order"
    else:
        rows = _overall_location_amplitudes(located)
        basis = "overall"
    location = candidate.strongest_location if candidate is not None else None
    if candidate is not None and candidate.location is not None:
        location = candidate.location.strongest_location or location
    hz_per_kmh = _hz_per_kmh(candidate)
    reference_speed = _reference_speed_kmh(candidate)
    speed_min, speed_max = _matched_speed_range(candidate)
    spectrum_location = _strongest_row_location(rows) or location
    return {
        "verdict": verdict.value,
        "confidence_level": (
            ConfidenceLevel.WEAK.value
            if verdict is DiagnosisVerdict.WEAK_EVIDENCE
            else level.value
            if candidate is not None and level is not None
            else None
        ),
        "finding_id": candidate.finding_id if candidate is not None else None,
        "source": str(candidate.suspected_source) if candidate is not None else None,
        "location": location,
        "zone": _zone(candidate, rows) if candidate is not None else None,
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
        "presence_ratio": _presence_ratio(candidate),
        "weak_reasons": weak_reasons,
        "guided_phases": _guided_phase_names(metadata.guided_phases),
        "speed_dependence": speed_dependence,
        "order_findings": _order_findings(candidate, level, test_run.findings),
        "amplitude_basis": basis,
        "location_amplitudes": rows,
        "amplitude_vs_speed": _amplitude_vs_speed(candidate),
        "spectrum": _spectrum(
            located,
            location=spectrum_location,
            centre_speed_kmh=reference_speed,
            refs=refs,
        ),
        "source_checks": _source_checks(
            candidate, test_run.findings, refs, samples, speed_dependence
        ),
        "conditions": _conditions(samples, refs),
    }


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
    """Reference data the order analysis used for this run."""

    tire_circumference_m: float | None
    final_drive_ratio: float | None
    gear_ratio: float | None


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
) -> list[LocationAmplitudeRow]:
    amps: dict[str, list[float]] = defaultdict(list)
    for point in candidate.matched_points:
        if point.amp > 0 and point.location:
            amps[point.location].append(point.amp)
    speed_samples: Counter[str] = Counter(
        location
        for sample, location in located
        if sample.speed_kmh is not None and sample.speed_kmh > 0
    )
    locations = sorted({location for _sample, location in located} | set(amps))
    medians: dict[str, float | None] = {
        location: median(amps[location]) if amps.get(location) else None for location in locations
    }
    presence: dict[str, float | None] = {
        location: (
            min(1.0, len(amps.get(location, ())) / speed_samples[location])
            if speed_samples[location]
            else None
        )
        for location in locations
    }
    return _with_ratios(medians, floors=_location_floors(located), presence=presence)


def _overall_location_amplitudes(
    located: Sequence[tuple[Sample, str]],
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
    return _with_ratios(
        p95,
        floors=_location_floors(located),
        presence=dict.fromkeys(locations),
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
        for point in candidate.matched_points
        if point.speed_kmh is not None and point.speed_kmh > 0
    )
    if not speeds:
        return None, None
    return percentile(speeds, 0.05), percentile(speeds, 0.95)


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


def _presence_ratio(candidate: Finding | None) -> float | None:
    if candidate is None or candidate.evidence is None:
        return None
    evidence = candidate.evidence
    if candidate.matched_points:
        return evidence.match_rate
    return evidence.presence_ratio


def _is_candidate(finding: Finding, candidate: Finding | None) -> bool:
    return candidate is not None and finding.finding_id == candidate.finding_id


def _order_findings(
    candidate: Finding | None,
    level: ConfidenceLevel | None,
    findings: Sequence[Finding],
) -> list[OrderFindingRow]:
    """Surfaced order-tracked findings, one per order, the diagnosed one first at its level.

    Orders are listed from Moderate up; a repeated order keeps its best-ranked
    finding. The diagnosed source's other order is listed once even when weak on
    its own: a mechanic reads T1 with T2 present differently from T1 alone.
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
                "presence_ratio": _presence_ratio(finding),
                "confidence_level": (
                    level if diagnosed and level is not None else finding.confidence_level
                ).value,
            }
        )
    return rows


# -- interpretation -----------------------------------------------------------


def _axle_zone(codes: Iterable[str]) -> str | None:
    axles = {code.split("_", 1)[0] for code in codes if code in WHEEL_LOCATION_CODES}
    return f"{axles.pop()}_axle" if len(axles) == 1 else None


def _zone(candidate: Finding, rows: Sequence[LocationAmplitudeRow]) -> str | None:
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
    if source is VibrationSource.DRIVELINE:
        if top_codes and top_codes[0] in _DRIVELINE_ZONE_CODES:
            return top_codes[0]
        return _axle_zone(top_codes) or "driveshaft_tunnel"
    if not top_codes:
        return None
    if len(top_codes) > 1 and source is VibrationSource.WHEEL_TIRE:
        wheels = [code for code in top_codes if code in WHEEL_LOCATION_CODES]
        if len(wheels) >= _ALL_WHEELS_MIN_CORNERS:
            return "all_wheels"
        return _axle_zone(top_codes) or top_codes[0]
    return top_codes[0]


def _weak_reasons(candidate: Finding | None, *, sensor_count: int) -> list[str]:
    if candidate is None:
        return []
    reasons: list[str] = []
    localized_source = candidate.suspected_source not in (
        VibrationSource.ENGINE,
        VibrationSource.DRIVELINE,
    )
    if localized_source and candidate.weak_spatial_separation:
        reasons.append("spread_across_locations")
    speed_min, speed_max = _matched_speed_range(candidate)
    if (
        speed_min is not None
        and speed_max is not None
        and speed_max - speed_min < _NARROW_SPEED_KMH
    ):
        reasons.append("narrow_speed_range")
    presence = _presence_ratio(candidate)
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
    samples: Sequence[Sample],
    speed_dependence: SpeedDependenceValue | None,
) -> list[SourceCheck]:
    rpm_source = _rpm_source(samples)
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
        reason: SourceCheckReason | None = None
        if refs.tire_circumference_m is None:
            reason = "no_tire_reference"
        elif source is not VibrationSource.WHEEL_TIRE and refs.final_drive_ratio is None:
            reason = "no_drive_reference"
        elif source is VibrationSource.ENGINE and rpm_source == "none":
            reason = "no_engine_reference"
        if reason is not None:
            checks.append({"source": str(source), "status": "not_testable", "reason": reason})
            continue
        estimated = source is VibrationSource.ENGINE and rpm_source == "estimated"
        checks.append(
            {
                "source": str(source),
                "status": "ruled_out",
                "reason": "rpm_estimated" if estimated else "no_matching_order",
            }
        )
    return checks


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
    the run.
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
    by_location = Counter(point.location for point in candidate.matched_points if point.location)
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
        if point.location == location and point.t_s is not None
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


def _rpm_source(samples: Sequence[Sample]) -> RpmSourceValue:
    measured = estimated = 0
    for sample in samples:
        if sample.engine_rpm is None or sample.engine_rpm <= 0:
            continue
        if sample.engine_rpm_source.strip().lower() in _MEASURED_RPM_EXCLUDED:
            estimated += 1
        else:
            measured += 1
    if measured and measured >= estimated:
        return "measured"
    return "estimated" if estimated else "none"


def _speed_source(samples: Sequence[Sample]) -> str | None:
    counts = Counter(
        sample.speed_source.strip().lower()
        for sample in samples
        if sample.speed_kmh is not None and sample.speed_kmh > 0 and sample.speed_source.strip()
    )
    return counts.most_common(1)[0][0] if counts else None


def _conditions(samples: Sequence[Sample], refs: _References) -> TestConditions:
    return {
        "speed_source": _speed_source(samples),
        "rpm_source": _rpm_source(samples),
        "tire_circumference_m": refs.tire_circumference_m,
        "final_drive_ratio": refs.final_drive_ratio,
        "gear_ratio": refs.gear_ratio,
    }


# -- spectrum -----------------------------------------------------------------


def _order_markers(refs: _References, speed_kmh: float) -> dict[str, float]:
    tire = refs.tire_circumference_m
    wheel = wheel_hz_from_speed_kmh(speed_kmh, tire) if tire is not None else None
    if wheel is None:
        return {}
    markers = {"T1": wheel, "T2": 2 * wheel}
    if refs.final_drive_ratio is not None:
        shaft = wheel * refs.final_drive_ratio
        markers |= {"P1": shaft, "P2": 2 * shaft}
        if refs.gear_ratio is not None:
            engine = shaft * refs.gear_ratio
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
    at_location = [sample for sample, label in located if label == location]
    speeds = sorted(
        sample.speed_kmh
        for sample in at_location
        if sample.speed_kmh is not None and sample.speed_kmh > 0
    )
    if not at_location or not speeds:
        return None
    centre = centre_speed_kmh if centre_speed_kmh is not None else median(speeds)
    window = [
        sample
        for sample in at_location
        if sample.speed_kmh is not None
        and abs(sample.speed_kmh - centre) <= _SPECTRUM_HALF_WINDOW_KMH
    ]
    if len(window) < _SPECTRUM_MIN_WINDOW_SAMPLES:
        window = [sample for sample in at_location if sample.speed_kmh is not None]
    window_speeds = [sample.speed_kmh for sample in window if sample.speed_kmh is not None]
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
        "order_markers": _order_markers(refs, window_centre),
    }
