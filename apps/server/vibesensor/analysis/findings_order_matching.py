"""Sample-to-hypothesis matching for order-tracking findings."""

from __future__ import annotations

from collections import defaultdict

from ..constants import ORDER_TOLERANCE_MIN_HZ, ORDER_TOLERANCE_REL
from ..domain_models import as_float_or_none as _as_float
from ._types import MatchedPoint, MetadataDict, PhaseLabels, Sample
from .findings_order_models import OrderMatchAccumulator
from .findings_speed_profile import _phase_to_str
from .helpers import (
    _estimate_strength_floor_amp_g,
    _location_label,
    _speed_bin_label,
)
from .order_analysis import OrderHypothesis


def match_samples_for_hypothesis(
    samples: list[Sample],
    cached_peaks: list[list[tuple[float, float]]],
    hypothesis: OrderHypothesis,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> OrderMatchAccumulator:
    """Match one hypothesis against all samples and accumulate evidence."""
    possible = 0
    matched = 0
    matched_amp: list[float] = []
    matched_floor: list[float] = []
    rel_errors: list[float] = []
    predicted_vals: list[float] = []
    measured_vals: list[float] = []
    matched_points: list[MatchedPoint] = []
    ref_sources: set[str] = set()
    possible_by_speed_bin: dict[str, int] = defaultdict(int)
    matched_by_speed_bin: dict[str, int] = defaultdict(int)
    possible_by_phase: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    possible_by_location: dict[str, int] = defaultdict(int)
    matched_by_location: dict[str, int] = defaultdict(int)
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    compliance = getattr(hypothesis, "path_compliance", 1.0)
    compliance_scale = compliance**0.5

    for sample_idx, sample in enumerate(samples):
        peaks = cached_peaks[sample_idx]
        if not peaks:
            continue
        predicted_hz, ref_source = hypothesis.predicted_hz(sample, metadata, tire_circumference_m)
        if predicted_hz is None or predicted_hz <= 0:
            continue
        possible += 1
        ref_sources.add(ref_source)

        sample_location = _location_label(sample, lang=lang)
        if sample_location:
            possible_by_location[sample_location] += 1
        sample_speed = _as_float(sample.get("speed_kmh"))
        sample_speed_bin = (
            _speed_bin_label(sample_speed)
            if sample_speed is not None and sample_speed > 0
            else None
        )
        if sample_speed_bin is not None:
            possible_by_speed_bin[sample_speed_bin] += 1

        phase_key: str | None = None
        if has_phases:
            assert per_sample_phases is not None
            phase = per_sample_phases[sample_idx]
            phase_key = str(phase.value if hasattr(phase, "value") else phase)
            possible_by_phase[phase_key] += 1

        tolerance_hz = max(
            ORDER_TOLERANCE_MIN_HZ,
            predicted_hz * ORDER_TOLERANCE_REL * compliance_scale,
        )
        best_hz, best_amp = min(peaks, key=lambda item: abs(item[0] - predicted_hz))
        delta_hz = abs(best_hz - predicted_hz)
        if delta_hz > tolerance_hz:
            continue

        matched += 1
        if sample_location:
            matched_by_location[sample_location] += 1
        if sample_speed_bin is not None:
            matched_by_speed_bin[sample_speed_bin] += 1
        if has_phases and phase_key is not None:
            matched_by_phase[phase_key] += 1

        rel_errors.append(delta_hz / max(1e-9, predicted_hz))
        matched_amp.append(best_amp)
        floor_amp = _estimate_strength_floor_amp_g(sample)
        matched_floor.append(max(0.0, floor_amp if floor_amp is not None else 0.0))
        predicted_vals.append(predicted_hz)
        measured_vals.append(best_hz)
        matched_points.append(
            {
                "t_s": _as_float(sample.get("t_s")),
                "speed_kmh": _as_float(sample.get("speed_kmh")),
                "predicted_hz": predicted_hz,
                "matched_hz": best_hz,
                "rel_error": delta_hz / max(1e-9, predicted_hz),
                "amp": best_amp,
                "location": sample_location,
                "phase": (
                    _phase_to_str(per_sample_phases[sample_idx])
                    if has_phases and per_sample_phases is not None
                    else None
                ),
            },
        )

    return OrderMatchAccumulator(
        possible=possible,
        matched=matched,
        matched_amp=matched_amp,
        matched_floor=matched_floor,
        rel_errors=rel_errors,
        predicted_vals=predicted_vals,
        measured_vals=measured_vals,
        matched_points=matched_points,
        ref_sources=ref_sources,
        possible_by_speed_bin=dict(possible_by_speed_bin),
        matched_by_speed_bin=dict(matched_by_speed_bin),
        possible_by_phase=dict(possible_by_phase),
        matched_by_phase=dict(matched_by_phase),
        possible_by_location=dict(possible_by_location),
        matched_by_location=dict(matched_by_location),
        has_phases=has_phases,
        compliance=compliance,
    )
