"""Boundary codecs for location-hotspot summary payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.domain import (
    LocationIntensitySummary,
    PhaseIntensitySummary,
    StrengthBucketDistribution,
    coerce_float,
    coerce_int,
)

__all__ = [
    "location_intensity_summaries_from_rows",
    "location_intensity_summary_from_mapping",
    "phase_intensity_summary_from_mapping",
    "strength_bucket_distribution_from_mapping",
]


def strength_bucket_distribution_from_mapping(raw: object) -> StrengthBucketDistribution:
    """Decode a raw bucket-distribution mapping into the typed domain value."""
    if not isinstance(raw, Mapping):
        return StrengthBucketDistribution()
    counts_raw = raw.get("counts")
    counts: dict[str, int] = {}
    if isinstance(counts_raw, Mapping):
        for key, value in counts_raw.items():
            try:
                counts[str(key)] = coerce_int(value)
            except (TypeError, ValueError):
                continue
    try:
        total = coerce_int(raw.get("total", 0))
    except (TypeError, ValueError):
        total = 0
    return StrengthBucketDistribution(
        total=total,
        counts=counts,
        percent_time_l0=_opt_float(raw.get("percent_time_l0")) or 0.0,
        percent_time_l1=_opt_float(raw.get("percent_time_l1")) or 0.0,
        percent_time_l2=_opt_float(raw.get("percent_time_l2")) or 0.0,
        percent_time_l3=_opt_float(raw.get("percent_time_l3")) or 0.0,
        percent_time_l4=_opt_float(raw.get("percent_time_l4")) or 0.0,
        percent_time_l5=_opt_float(raw.get("percent_time_l5")) or 0.0,
    )


def phase_intensity_summary_from_mapping(raw: object) -> PhaseIntensitySummary:
    """Decode a raw phase-intensity mapping into the typed domain value."""
    if not isinstance(raw, Mapping):
        return PhaseIntensitySummary()
    try:
        count = coerce_int(raw.get("count", 0))
    except (TypeError, ValueError):
        count = 0
    return PhaseIntensitySummary(
        count=count,
        mean_intensity_db=_opt_float(raw.get("mean_intensity_db")),
        max_intensity_db=_opt_float(raw.get("max_intensity_db")),
    )


def location_intensity_summary_from_mapping(raw: Mapping[str, object]) -> LocationIntensitySummary:
    """Decode one raw location-intensity mapping into the typed domain value."""
    sample_count_raw = raw.get("sample_count", raw.get("samples", 0))
    try:
        sample_count = coerce_int(sample_count_raw)
    except (TypeError, ValueError):
        sample_count = 0

    sample_coverage_ratio_raw = raw.get("sample_coverage_ratio", 0.0)
    try:
        sample_coverage_ratio = coerce_float(sample_coverage_ratio_raw)
    except (TypeError, ValueError):
        sample_coverage_ratio = 0.0

    usable_sample_count = _opt_int(raw.get("usable_sample_count"))
    usable_sample_coverage_ratio = _opt_float(raw.get("usable_sample_coverage_ratio"))
    usable_sample_coverage_warning_raw = raw.get("usable_sample_coverage_warning")
    usable_sample_coverage_warning = (
        bool(usable_sample_coverage_warning_raw)
        if usable_sample_coverage_warning_raw is not None
        else None
    )

    phase_intensity_raw = raw.get("phase_intensity")
    phase_intensity: dict[str, PhaseIntensitySummary] | None = None
    if isinstance(phase_intensity_raw, Mapping):
        parsed_phase_intensity = {
            str(phase_key): phase_intensity_summary_from_mapping(stats)
            for phase_key, stats in phase_intensity_raw.items()
            if isinstance(stats, Mapping)
        }
        phase_intensity = parsed_phase_intensity or None

    return LocationIntensitySummary(
        location=str(raw.get("location", "")),
        partial_coverage=bool(raw.get("partial_coverage", False)),
        sample_count=sample_count,
        sample_coverage_ratio=sample_coverage_ratio,
        sample_coverage_warning=bool(raw.get("sample_coverage_warning", False)),
        usable_sample_count=usable_sample_count,
        usable_sample_coverage_ratio=usable_sample_coverage_ratio,
        usable_sample_coverage_warning=usable_sample_coverage_warning,
        mean_intensity_db=_opt_float(raw.get("mean_intensity_db")),
        p50_intensity_db=_opt_float(raw.get("p50_intensity_db")),
        p95_intensity_db=_opt_float(raw.get("p95_intensity_db")),
        max_intensity_db=_opt_float(raw.get("max_intensity_db")),
        dropped_frames_delta=_opt_float(raw.get("dropped_frames_delta")),
        queue_overflow_drops_delta=_opt_float(raw.get("queue_overflow_drops_delta")),
        strength_bucket_distribution=strength_bucket_distribution_from_mapping(
            raw.get("strength_bucket_distribution"),
        ),
        phase_intensity=phase_intensity,
    )


def location_intensity_summaries_from_rows(
    rows: Sequence[object],
) -> list[LocationIntensitySummary]:
    """Decode a mixed row sequence into typed location-intensity summaries."""
    summaries: list[LocationIntensitySummary] = []
    for row in rows:
        if isinstance(row, LocationIntensitySummary):
            summaries.append(row)
        elif isinstance(row, Mapping):
            summaries.append(location_intensity_summary_from_mapping(row))
    return summaries


def _opt_float(value: object) -> float | None:
    if value is None or not isinstance(value, (int, float, str)):
        return None
    try:
        return coerce_float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: object) -> int | None:
    if value is None or not isinstance(value, (int, float, str)):
        return None
    try:
        return coerce_int(value)
    except (TypeError, ValueError):
        return None
