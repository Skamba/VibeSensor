"""Canonical reporting summary boundary for history and PDF preparation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from vibesensor.domain import LocationIntensitySummary
from vibesensor.shared.boundaries.codecs.scalars import (
    coerce_count,
    optional_float,
    text_or_none,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.summary_fields.hotspot import (
    location_intensity_summaries_from_rows,
)
from vibesensor.shared.types.analysis_views import PeakTableRow
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "NormalizedReportSummary",
    "ReportWholeRunContextInterval",
    "ReportSummaryNormalizer",
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
class ReportWholeRunContextInterval:
    """Typed whole-run context interval normalized for report/history preparation."""

    segment_index: int
    phase: str
    load_state: str
    start_window_index: int
    end_window_index: int
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    speed_band: str | None
    full_context_window_count: int
    partial_context_window_count: int
    missing_context_window_count: int

    @property
    def window_count(self) -> int:
        return (self.end_window_index - self.start_window_index) + 1


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
    whole_run_context_intervals: tuple[ReportWholeRunContextInterval, ...]


class ReportSummaryNormalizer:
    """Normalize one summary payload into the canonical report-side typed shape."""

    __slots__ = ("_metadata", "_payload")

    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = payload
        self._metadata = self._summary_run_metadata()

    def normalize(self) -> NormalizedReportSummary:
        return NormalizedReportSummary(
            run_id=self._summary_run_id(),
            metadata=self._metadata,
            report_date=self._summary_report_date(),
            duration_s=optional_float(self._payload.get("duration_s")),
            record_length=text_or_none(self._payload.get("record_length")),
            start_time_utc=text_or_none(self._payload.get("start_time_utc")),
            end_time_utc=text_or_none(self._payload.get("end_time_utc")),
            sample_count=coerce_count(self._payload.get("rows")),
            sensor_count=coerce_count(self._payload.get("sensor_count_used")),
            active_sensor_locations=self._active_sensor_locations(),
            sensor_intensity_rows=self._sensor_intensity_rows(),
            peak_table_rows=self._peak_table_rows(),
            timeline_intervals=self._timeline_intervals(),
            whole_run_context_intervals=self._whole_run_context_intervals(),
        )

    def _summary_run_metadata(self) -> RunMetadata | None:
        metadata_payload = self._payload.get("metadata")
        if not isinstance(metadata_payload, Mapping):
            return None
        if not metadata_payload:
            return None
        top_level_run_id = text_or_none(self._payload.get("run_id"))
        metadata_run_id = text_or_none(metadata_payload.get("run_id"))
        if metadata_run_id is None:
            raise ValueError("report summary metadata must include canonical nested run_id")
        if top_level_run_id is not None and metadata_run_id != top_level_run_id:
            raise ValueError("report summary metadata run_id must match the top-level run_id")
        return run_metadata_from_mapping(metadata_payload)

    def _summary_run_id(self) -> str:
        raw_run_id = text_or_none(self._payload.get("run_id"))
        if raw_run_id is not None:
            return raw_run_id
        if self._metadata is not None and self._metadata.run_id:
            return self._metadata.run_id
        return "unknown"

    def _summary_report_date(self) -> str | None:
        return text_or_none(self._payload.get("report_date")) or (
            text_or_none(self._metadata.report_date) if self._metadata is not None else None
        )

    def _active_sensor_locations(self) -> tuple[str, ...]:
        connected = self._payload.get("sensor_locations_connected_throughout")
        locations = connected if isinstance(connected, list) else []
        return tuple(str(location).strip() for location in locations if str(location).strip())

    def _sensor_intensity_rows(self) -> tuple[LocationIntensitySummary, ...]:
        raw_rows = self._payload.get("sensor_intensity_by_location")
        rows = raw_rows if isinstance(raw_rows, list) else []
        return tuple(location_intensity_summaries_from_rows(rows))

    def _peak_table_rows(self) -> tuple[PeakTableRow, ...]:
        plots = self._payload.get("plots")
        if not isinstance(plots, Mapping):
            return ()
        raw_rows = plots.get("peaks_table")
        if not isinstance(raw_rows, list):
            return ()
        return tuple(cast(PeakTableRow, row) for row in raw_rows if isinstance(row, Mapping))

    def _timeline_intervals(self) -> tuple[ReportTimelineInterval, ...]:
        raw_timeline = self._payload.get("phase_timeline")
        if not isinstance(raw_timeline, list):
            return ()
        intervals: list[ReportTimelineInterval] = []
        for row in raw_timeline:
            if not isinstance(row, Mapping):
                continue
            phase = text_or_none(row.get("phase"))
            if phase is None:
                continue
            intervals.append(
                ReportTimelineInterval(
                    phase=phase,
                    start_t_s=optional_float(row.get("start_t_s")),
                    end_t_s=optional_float(row.get("end_t_s")),
                    speed_min_kmh=optional_float(row.get("speed_min_kmh")),
                    speed_max_kmh=optional_float(row.get("speed_max_kmh")),
                    has_fault_evidence=bool(row.get("has_fault_evidence")),
                )
            )
        return tuple(intervals)

    def _whole_run_context_intervals(self) -> tuple[ReportWholeRunContextInterval, ...]:
        raw_intervals = self._payload.get("whole_run_context_intervals")
        if not isinstance(raw_intervals, list):
            return ()
        intervals: list[ReportWholeRunContextInterval] = []
        for row in raw_intervals:
            if not isinstance(row, Mapping):
                continue
            phase = text_or_none(row.get("phase"))
            load_state = text_or_none(row.get("load_state"))
            if phase is None or load_state is None:
                continue
            intervals.append(
                ReportWholeRunContextInterval(
                    segment_index=coerce_count(row.get("segment_index")),
                    phase=phase,
                    load_state=load_state,
                    start_window_index=coerce_count(row.get("start_window_index")),
                    end_window_index=coerce_count(row.get("end_window_index")),
                    start_t_s=optional_float(row.get("start_t_s")),
                    end_t_s=optional_float(row.get("end_t_s")),
                    speed_min_kmh=optional_float(row.get("speed_min_kmh")),
                    speed_max_kmh=optional_float(row.get("speed_max_kmh")),
                    speed_band=text_or_none(row.get("speed_band")),
                    full_context_window_count=coerce_count(row.get("full_context_window_count")),
                    partial_context_window_count=coerce_count(
                        row.get("partial_context_window_count")
                    ),
                    missing_context_window_count=coerce_count(
                        row.get("missing_context_window_count")
                    ),
                )
            )
        return tuple(intervals)


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

    return ReportSummaryNormalizer(payload).normalize()
