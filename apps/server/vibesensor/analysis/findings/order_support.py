"""Shared pure helpers used by order-finding assembly."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ...runlog import as_float_or_none as _as_float
from ..phase_segmentation import DrivingPhase

_PHASE_ONSET_RELEVANT: frozenset[str] = frozenset(
    {
        DrivingPhase.ACCELERATION.value,
        DrivingPhase.DECELERATION.value,
        DrivingPhase.COAST_DOWN.value,
    }
)


def compute_matched_speed_phase_evidence(
    matched_points: list[dict[str, Any]],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
    speed_profile_from_points,
) -> tuple[float | None, list[float], str | None, dict[str, Any], str | None]:
    """Derive speed-profile and phase-evidence from matched points."""
    cruise_value = DrivingPhase.CRUISE.value
    speed_points: list[tuple[float, float]] = []
    speed_phase_weights: list[float] = []
    for point in matched_points:
        point_speed = _as_float(point.get("speed_kmh"))
        point_amp = _as_float(point.get("amp"))
        if point_speed is None or point_amp is None:
            continue
        speed_points.append((point_speed, point_amp))
        phase = str(point.get("phase") or "")
        if phase == cruise_value:
            speed_phase_weights.append(3.0)
        elif phase in _PHASE_ONSET_RELEVANT:
            speed_phase_weights.append(0.3)
        else:
            speed_phase_weights.append(1.0)

    peak_speed_kmh, speed_window_kmh, strongest_speed_band = speed_profile_from_points(
        speed_points,
        allowed_speed_bins=[focused_speed_band] if focused_speed_band else None,
        phase_weights=speed_phase_weights if speed_phase_weights else None,
    )
    if not strongest_speed_band:
        strongest_speed_band = hotspot_speed_band
    if focused_speed_band and not strongest_speed_band:
        strongest_speed_band = focused_speed_band

    matched_phase_strs = [
        str(point.get("phase") or "") for point in matched_points if point.get("phase")
    ]
    cruise_matched = sum(1 for phase in matched_phase_strs if phase == cruise_value)
    phase_evidence: dict[str, Any] = {
        "cruise_fraction": cruise_matched / len(matched_phase_strs) if matched_phase_strs else 0.0,
        "phases_detected": sorted(set(matched_phase_strs)),
    }
    dominant_phase: str | None = None
    onset_phase_labels = [phase for phase in matched_phase_strs if phase in _PHASE_ONSET_RELEVANT]
    if onset_phase_labels and len(onset_phase_labels) >= max(2, len(matched_points) // 2):
        top_phase, top_count = Counter(onset_phase_labels).most_common(1)[0]
        if top_count / len(matched_points) >= 0.50:
            dominant_phase = top_phase

    return (
        peak_speed_kmh,
        list(speed_window_kmh) if speed_window_kmh is not None else [],
        strongest_speed_band or None,
        phase_evidence,
        dominant_phase,
    )


def compute_phase_stats(
    has_phases: bool,
    possible_by_phase: dict[str, int],
    matched_by_phase: dict[str, int],
    *,
    min_match_rate: float,
    min_match_points: int,
) -> tuple[dict[str, float] | None, int]:
    """Compute per-phase confidence and count phases with sufficient evidence."""
    if not has_phases or not possible_by_phase:
        return None, 0
    per_phase_confidence: dict[str, float] = {}
    phases_with_evidence = 0
    for phase_key, phase_possible in possible_by_phase.items():
        phase_matched = matched_by_phase.get(phase_key, 0)
        per_phase_confidence[phase_key] = phase_matched / max(1, phase_possible)
        if phase_matched >= min_match_points and per_phase_confidence[phase_key] >= min_match_rate:
            phases_with_evidence += 1
    return per_phase_confidence, phases_with_evidence


def compute_amplitude_and_error_stats(
    matched_amp: list[float],
    matched_floor: list[float],
    rel_errors: list[float],
    predicted_vals: list[float],
    measured_vals: list[float],
    matched_points: list[dict[str, Any]],
    *,
    constant_speed: bool,
    corr_abs_clamped,
) -> tuple[float, float, float, float, float | None]:
    """Compute amplitude, floor, relative-error, and correlation statistics."""
    mean_amp = (sum(matched_amp) / len(matched_amp)) if matched_amp else 0.0
    mean_floor = (sum(matched_floor) / len(matched_floor)) if matched_floor else 0.0
    mean_rel_err = (sum(rel_errors) / len(rel_errors)) if rel_errors else 1.0
    corr = corr_abs_clamped(predicted_vals, measured_vals) if len(matched_points) >= 3 else None
    if constant_speed:
        corr = None
    corr_val = corr if corr is not None else 0.0
    return mean_amp, mean_floor, mean_rel_err, corr_val, corr


def apply_localization_override(
    *,
    per_location_dominant: bool,
    unique_match_locations: set[str],
    connected_locations: set[str],
    matched: int,
    no_wheel_override: bool,
    localization_confidence: float,
    weak_spatial_separation: bool,
    min_match_points: int,
) -> tuple[float, bool]:
    """Adjust localization confidence when only one connected sensor matched."""
    if (
        per_location_dominant
        and len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and not no_wheel_override
    ):
        localization_confidence = min(1.0, 0.50 + 0.15 * (len(connected_locations) - 1))
        weak_spatial_separation = False
    elif (
        len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and matched >= min_match_points
        and not no_wheel_override
    ):
        localization_confidence = max(
            localization_confidence,
            min(1.0, 0.40 + 0.10 * (len(connected_locations) - 1)),
        )
        weak_spatial_separation = False
    return localization_confidence, weak_spatial_separation
