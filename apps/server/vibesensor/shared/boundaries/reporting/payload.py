"""Canonical reporting payload boundary for history and PDF preparation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from vibesensor.domain import LocationIntensitySummary, coerce_float, coerce_int
from vibesensor.shared.boundaries.location_hotspot_codec import (
    location_intensity_summaries_from_rows,
)
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.types.analysis_views import PeakTableRow
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "NormalizedReportSummary",
    "ReportTimelineInterval",
    "has_projectable_report_payload",
    "report_summary_from_mapping",
    "require_projectable_report_payload",
]


@dataclass(frozen=True, slots=True)
class ReportTimelineInterval:
    """Typed report summary interval normalized from the phase-timeline payload."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    has_fault_evidence: bool


@dataclass(frozen=True, slots=True)
class NormalizedReportSummary:
    """Typed report boundary object shared by report facts and renderer mapping."""

    run_id: str
    metadata: RunMetadata | None
    report_date: str | None
    duration_s: float | None
    record_length: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_count: int
    sensor_count: int
    active_sensor_locations: tuple[str, ...]
    sensor_intensity_rows: tuple[LocationIntensitySummary, ...]
    peak_table_rows: tuple[PeakTableRow, ...]
    timeline_intervals: tuple[ReportTimelineInterval, ...]


def has_projectable_report_payload(payload: Mapping[str, object]) -> bool:
    """Return whether *payload* has the minimum shape needed for report projection."""

    findings = payload.get("findings")
    top_causes = payload.get("top_causes")
    return isinstance(findings, list) or isinstance(top_causes, list)


def require_projectable_report_payload(payload: Mapping[str, object]) -> None:
    """Raise when *payload* cannot be projected into the canonical report shape."""

    if not has_projectable_report_payload(payload):
        raise ValueError(
            "Report payload must include findings or top_causes lists for report preparation"
        )


def report_summary_from_mapping(payload: Mapping[str, object]) -> NormalizedReportSummary:
    """Normalize one summary payload into the canonical report-side typed shape."""

    typed_metadata = _summary_run_metadata(payload)
    return NormalizedReportSummary(
        run_id=_summary_run_id(payload, typed_metadata),
        metadata=typed_metadata,
        report_date=_summary_report_date(payload, typed_metadata),
        duration_s=_optional_float(payload.get("duration_s")),
        record_length=_normalized_text(payload.get("record_length")),
        start_time_utc=_normalized_text(payload.get("start_time_utc")),
        end_time_utc=_normalized_text(payload.get("end_time_utc")),
        sample_count=_coerce_count(payload.get("rows")),
        sensor_count=_coerce_count(payload.get("sensor_count_used")),
        active_sensor_locations=_active_sensor_locations(payload),
        sensor_intensity_rows=_sensor_intensity_rows(payload),
        peak_table_rows=_peak_table_rows(payload),
        timeline_intervals=_timeline_intervals(payload),
    )


def _summary_run_metadata(payload: Mapping[str, object]) -> RunMetadata | None:
    metadata_payload = payload.get("metadata")
    if not isinstance(metadata_payload, Mapping):
        return None
    if not metadata_payload:
        return None
    top_level_run_id = _normalized_text(payload.get("run_id"))
    metadata_run_id = _normalized_text(metadata_payload.get("run_id"))
    if metadata_run_id is None:
        raise ValueError("report summary metadata must include canonical nested run_id")
    if top_level_run_id is not None and metadata_run_id != top_level_run_id:
        raise ValueError("report summary metadata run_id must match the top-level run_id")
    return run_metadata_from_mapping(metadata_payload)


def _summary_run_id(payload: Mapping[str, object], metadata: RunMetadata | None) -> str:
    raw_run_id = _normalized_text(payload.get("run_id"))
    if raw_run_id is not None:
        return raw_run_id
    if metadata is not None and metadata.run_id:
        return metadata.run_id
    return "unknown"


def _summary_report_date(payload: Mapping[str, object], metadata: RunMetadata | None) -> str | None:
    return _normalized_text(payload.get("report_date")) or (
        _normalized_text(metadata.report_date) if metadata is not None else None
    )


def _active_sensor_locations(payload: Mapping[str, object]) -> tuple[str, ...]:
    connected = payload.get("sensor_locations_connected_throughout")
    locations = connected if isinstance(connected, list) else []
    active = tuple(str(location).strip() for location in locations if str(location).strip())
    if active:
        return active
    fallback = payload.get("sensor_locations")
    fallback_locations = fallback if isinstance(fallback, list) else []
    return tuple(str(location).strip() for location in fallback_locations if str(location).strip())


def _sensor_intensity_rows(payload: Mapping[str, object]) -> tuple[LocationIntensitySummary, ...]:
    raw_rows = payload.get("sensor_intensity_by_location")
    rows = raw_rows if isinstance(raw_rows, list) else []
    return tuple(location_intensity_summaries_from_rows(rows))


def _peak_table_rows(payload: Mapping[str, object]) -> tuple[PeakTableRow, ...]:
    plots = payload.get("plots")
    if not isinstance(plots, Mapping):
        return ()
    raw_rows = plots.get("peaks_table")
    if not isinstance(raw_rows, list):
        return ()
    return tuple(cast(PeakTableRow, row) for row in raw_rows if isinstance(row, Mapping))


def _timeline_intervals(payload: Mapping[str, object]) -> tuple[ReportTimelineInterval, ...]:
    raw_timeline = payload.get("phase_timeline")
    if not isinstance(raw_timeline, list):
        return ()
    intervals: list[ReportTimelineInterval] = []
    for row in raw_timeline:
        if not isinstance(row, Mapping):
            continue
        phase = _normalized_text(row.get("phase"))
        if phase is None:
            continue
        intervals.append(
            ReportTimelineInterval(
                phase=phase,
                start_t_s=_optional_float(row.get("start_t_s")),
                end_t_s=_optional_float(row.get("end_t_s")),
                speed_min_kmh=_optional_float(row.get("speed_min_kmh")),
                speed_max_kmh=_optional_float(row.get("speed_max_kmh")),
                has_fault_evidence=bool(row.get("has_fault_evidence")),
            )
        )
    return tuple(intervals)


def _normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return coerce_float(value)
    except (TypeError, ValueError):
        return None


def _coerce_count(value: object) -> int:
    if value is None:
        return 0
    try:
        return coerce_int(value)
    except (TypeError, ValueError):
        return 0
