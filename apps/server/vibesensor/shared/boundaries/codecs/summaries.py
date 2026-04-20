"""Boundary codecs for persisted speed/phase summary snapshots."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import DrivingPhaseSummary, SpeedProfileSummary
from vibesensor.shared.boundaries.codecs.scalars import optional_float
from vibesensor.shared.types.json_types import JsonObject

__all__ = [
    "driving_phase_summary_from_mapping",
    "driving_phase_summary_to_payload",
    "speed_profile_summary_from_mapping",
    "speed_profile_summary_to_payload",
]


def speed_profile_summary_from_mapping(payload: object) -> SpeedProfileSummary:
    """Decode one persisted speed-summary payload into the domain snapshot."""
    if not isinstance(payload, Mapping):
        return SpeedProfileSummary()
    return SpeedProfileSummary(
        min_kmh=optional_float(payload.get("min_kmh")),
        max_kmh=optional_float(payload.get("max_kmh")),
        mean_kmh=optional_float(payload.get("mean_kmh")),
        stddev_kmh=optional_float(payload.get("stddev_kmh")),
        range_kmh=optional_float(payload.get("range_kmh")),
        steady_speed=_bool_or(payload.get("steady_speed")),
        sample_count=_int_or(payload.get("sample_count")),
    )


def speed_profile_summary_to_payload(summary: SpeedProfileSummary) -> JsonObject:
    """Project a typed speed-summary snapshot to a JSON-safe payload."""
    return {
        "min_kmh": summary.min_kmh,
        "max_kmh": summary.max_kmh,
        "mean_kmh": summary.mean_kmh,
        "stddev_kmh": summary.stddev_kmh,
        "range_kmh": summary.range_kmh,
        "steady_speed": summary.steady_speed,
        "sample_count": summary.sample_count,
    }


def driving_phase_summary_from_mapping(payload: object) -> DrivingPhaseSummary:
    """Decode one persisted phase-summary payload into the domain snapshot."""
    if not isinstance(payload, Mapping):
        return DrivingPhaseSummary()

    phase_counts: dict[str, int] = {}
    raw_counts = payload.get("phase_counts")
    if isinstance(raw_counts, Mapping):
        for key, value in raw_counts.items():
            if isinstance(key, str) and (parsed_count := _int_from(value)) is not None:
                phase_counts[key] = parsed_count

    phase_pcts: dict[str, float] = {}
    raw_pcts = payload.get("phase_pcts")
    if isinstance(raw_pcts, Mapping):
        for key, value in raw_pcts.items():
            if isinstance(key, str) and (parsed_pct := _float_from(value)) is not None:
                phase_pcts[key] = parsed_pct

    return DrivingPhaseSummary(
        phase_counts=phase_counts,
        phase_pcts=phase_pcts,
        total_samples=_int_or(payload.get("total_samples")),
        segment_count=_int_or(payload.get("segment_count")),
        has_cruise=phase_counts.get("cruise", 0) > 0,
        has_acceleration=phase_counts.get("acceleration", 0) > 0,
        cruise_pct=phase_pcts.get("cruise", 0.0),
        idle_pct=phase_pcts.get("idle", 0.0),
        speed_unknown_pct=phase_pcts.get("speed_unknown", 0.0),
    )


def driving_phase_summary_to_payload(summary: DrivingPhaseSummary) -> JsonObject:
    """Project a typed phase-summary snapshot to a JSON-safe payload."""
    return {
        "phase_counts": dict(summary.phase_counts),
        "phase_pcts": dict(summary.phase_pcts),
        "total_samples": summary.total_samples,
        "segment_count": summary.segment_count,
        "has_cruise": summary.has_cruise,
        "has_acceleration": summary.has_acceleration,
        "cruise_pct": summary.cruise_pct,
        "idle_pct": summary.idle_pct,
        "speed_unknown_pct": summary.speed_unknown_pct,
    }


def _float_from(value: object) -> float | None:
    return optional_float(value)


def _int_from(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _int_or(value: object, default: int = 0) -> int:
    parsed = _int_from(value)
    return parsed if parsed is not None else default


def _bool_or(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default
