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
from vibesensor.shared.types.history_analysis_contracts import LocationProofBasis
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "NormalizedReportSummary",
    "ReportOrderHarmonicEvidenceSummary",
    "ReportOrderTracePhaseSupport",
    "ReportOrderTraceSupportInterval",
    "ReportSpatialLocationSummary",
    "ReportWholeRunContextInterval",
    "ReportWholeRunOrderSummary",
    "ReportWholeRunSpatialSummary",
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
class ReportOrderTraceSupportInterval:
    """Typed persisted support interval normalized for report/history consumers."""

    interval_index: int
    start_window_index: int
    end_window_index: int
    matched_window_count: int
    support_ratio: float
    start_t_s: float | None
    end_t_s: float | None
    phase: str | None
    load_state: str | None
    speed_band: str | None
    mean_relative_error: float | None


@dataclass(frozen=True, slots=True)
class ReportOrderTracePhaseSupport:
    """Typed persisted phase-support row for one whole-run order summary."""

    phase: str
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float


@dataclass(frozen=True, slots=True)
class ReportOrderHarmonicEvidenceSummary:
    """Typed persisted harmonic evidence row for one whole-run order summary."""

    harmonic: int
    order_label: str
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float
    reference_coverage_ratio: float
    contiguous_support_ratio: float
    lock_score: float
    mean_relative_error: float | None
    relative_error_stddev: float | None
    drift_score: float
    peak_intensity_db: float | None
    mean_vibration_strength_db: float | None


@dataclass(frozen=True, slots=True)
class ReportWholeRunOrderSummary:
    """Typed persisted whole-run order summary for report/history reload paths."""

    hypothesis_key: str
    suspected_source: str
    order_family: str
    order_label: str
    total_window_count: int
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float
    reference_coverage_ratio: float
    longest_contiguous_support_window_count: int
    contiguous_support_ratio: float
    support_intervals: tuple[ReportOrderTraceSupportInterval, ...]
    phase_support: tuple[ReportOrderTracePhaseSupport, ...]
    harmonic_summaries: tuple[ReportOrderHarmonicEvidenceSummary, ...]
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    exemplar_interval_index: int | None
    dominant_phase: str | None
    dominant_speed_band: str | None
    strongest_location: str | None
    mean_relative_error: float | None
    relative_error_stddev: float | None
    drift_score: float
    lock_score: float
    peak_intensity_db: float | None
    mean_vibration_strength_db: float | None
    ref_sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportSpatialLocationSummary:
    """Typed persisted per-location spatial evidence row for report/history reload."""

    location: str
    sensor_ids: tuple[str, ...]
    supporting_window_count: int
    support_ratio: float
    coherent_window_count: int
    coherence_ratio: float | None
    peak_intensity_db: float | None
    mean_vibration_strength_db: float | None


@dataclass(frozen=True, slots=True)
class ReportWholeRunSpatialSummary:
    """Typed persisted whole-run spatial summary for report/history reload paths."""

    candidate_key: str
    suspected_source: str
    proof_basis: LocationProofBasis
    total_window_count: int
    supporting_window_count: int
    supporting_sensor_count: int
    coherent_window_count: int
    coherence_ratio: float | None
    dominant_location: str | None
    runner_up_location: str | None
    location_separation_db: float | None
    dominance_ratio: float | None
    ambiguous_location: bool
    weak_spatial_separation: bool
    location_summaries: tuple[ReportSpatialLocationSummary, ...]


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
    whole_run_order_summaries: tuple[ReportWholeRunOrderSummary, ...]
    whole_run_spatial_summaries: tuple[ReportWholeRunSpatialSummary, ...]


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
            whole_run_order_summaries=self._whole_run_order_summaries(),
            whole_run_spatial_summaries=self._whole_run_spatial_summaries(),
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

    def _whole_run_order_summaries(self) -> tuple[ReportWholeRunOrderSummary, ...]:
        raw_summaries = self._payload.get("whole_run_order_summaries")
        if not isinstance(raw_summaries, list):
            return ()
        summaries: list[ReportWholeRunOrderSummary] = []
        for row in raw_summaries:
            if not isinstance(row, Mapping):
                continue
            hypothesis_key = text_or_none(row.get("hypothesis_key"))
            suspected_source = text_or_none(row.get("suspected_source"))
            order_family = text_or_none(row.get("order_family"))
            order_label = text_or_none(row.get("order_label"))
            if (
                hypothesis_key is None
                or suspected_source is None
                or order_family is None
                or order_label is None
            ):
                continue
            summaries.append(
                ReportWholeRunOrderSummary(
                    hypothesis_key=hypothesis_key,
                    suspected_source=suspected_source,
                    order_family=order_family,
                    order_label=order_label,
                    total_window_count=coerce_count(row.get("total_window_count")),
                    eligible_window_count=coerce_count(row.get("eligible_window_count")),
                    matched_window_count=coerce_count(row.get("matched_window_count")),
                    support_ratio=optional_float(row.get("support_ratio")) or 0.0,
                    reference_coverage_ratio=optional_float(row.get("reference_coverage_ratio"))
                    or 0.0,
                    longest_contiguous_support_window_count=coerce_count(
                        row.get("longest_contiguous_support_window_count")
                    ),
                    contiguous_support_ratio=optional_float(row.get("contiguous_support_ratio"))
                    or 0.0,
                    support_intervals=self._order_support_intervals(row.get("support_intervals")),
                    phase_support=self._order_phase_support_rows(row.get("phase_support")),
                    harmonic_summaries=self._order_harmonic_summaries(
                        row.get("harmonic_summaries")
                    ),
                    stable_frequency_min_hz=optional_float(row.get("stable_frequency_min_hz")),
                    stable_frequency_max_hz=optional_float(row.get("stable_frequency_max_hz")),
                    exemplar_interval_index=self._optional_count(
                        row.get("exemplar_interval_index")
                    ),
                    dominant_phase=text_or_none(row.get("dominant_phase")),
                    dominant_speed_band=text_or_none(row.get("dominant_speed_band")),
                    strongest_location=text_or_none(row.get("strongest_location")),
                    mean_relative_error=optional_float(row.get("mean_relative_error")),
                    relative_error_stddev=optional_float(row.get("relative_error_stddev")),
                    drift_score=optional_float(row.get("drift_score")) or 0.0,
                    lock_score=optional_float(row.get("lock_score")) or 0.0,
                    peak_intensity_db=optional_float(row.get("peak_intensity_db")),
                    mean_vibration_strength_db=optional_float(
                        row.get("mean_vibration_strength_db")
                    ),
                    ref_sources=self._order_ref_sources(row.get("ref_sources")),
                )
            )
        return tuple(summaries)

    def _whole_run_spatial_summaries(self) -> tuple[ReportWholeRunSpatialSummary, ...]:
        raw_summaries = self._payload.get("whole_run_spatial_summaries")
        if not isinstance(raw_summaries, list):
            return ()
        summaries: list[ReportWholeRunSpatialSummary] = []
        for row in raw_summaries:
            if not isinstance(row, Mapping):
                continue
            candidate_key = text_or_none(row.get("candidate_key"))
            suspected_source = text_or_none(row.get("suspected_source"))
            proof_basis = self._proof_basis(row.get("proof_basis"))
            if candidate_key is None or suspected_source is None or proof_basis is None:
                continue
            summaries.append(
                ReportWholeRunSpatialSummary(
                    candidate_key=candidate_key,
                    suspected_source=suspected_source,
                    proof_basis=proof_basis,
                    total_window_count=coerce_count(row.get("total_window_count")),
                    supporting_window_count=coerce_count(row.get("supporting_window_count")),
                    supporting_sensor_count=coerce_count(row.get("supporting_sensor_count")),
                    coherent_window_count=coerce_count(row.get("coherent_window_count")),
                    coherence_ratio=optional_float(row.get("coherence_ratio")),
                    dominant_location=text_or_none(row.get("dominant_location")),
                    runner_up_location=text_or_none(row.get("runner_up_location")),
                    location_separation_db=optional_float(row.get("location_separation_db")),
                    dominance_ratio=optional_float(row.get("dominance_ratio")),
                    ambiguous_location=bool(row.get("ambiguous_location")),
                    weak_spatial_separation=bool(row.get("weak_spatial_separation")),
                    location_summaries=self._spatial_location_summaries(
                        row.get("location_summaries")
                    ),
                )
            )
        return tuple(summaries)

    def _order_support_intervals(
        self,
        raw_intervals: object,
    ) -> tuple[ReportOrderTraceSupportInterval, ...]:
        if not isinstance(raw_intervals, list):
            return ()
        intervals: list[ReportOrderTraceSupportInterval] = []
        for row in raw_intervals:
            if not isinstance(row, Mapping):
                continue
            intervals.append(
                ReportOrderTraceSupportInterval(
                    interval_index=coerce_count(row.get("interval_index")),
                    start_window_index=coerce_count(row.get("start_window_index")),
                    end_window_index=coerce_count(row.get("end_window_index")),
                    matched_window_count=coerce_count(row.get("matched_window_count")),
                    support_ratio=optional_float(row.get("support_ratio")) or 0.0,
                    start_t_s=optional_float(row.get("start_t_s")),
                    end_t_s=optional_float(row.get("end_t_s")),
                    phase=text_or_none(row.get("phase")),
                    load_state=text_or_none(row.get("load_state")),
                    speed_band=text_or_none(row.get("speed_band")),
                    mean_relative_error=optional_float(row.get("mean_relative_error")),
                )
            )
        return tuple(intervals)

    def _order_phase_support_rows(
        self,
        raw_phase_rows: object,
    ) -> tuple[ReportOrderTracePhaseSupport, ...]:
        if not isinstance(raw_phase_rows, list):
            return ()
        rows: list[ReportOrderTracePhaseSupport] = []
        for row in raw_phase_rows:
            if not isinstance(row, Mapping):
                continue
            phase = text_or_none(row.get("phase"))
            if phase is None:
                continue
            rows.append(
                ReportOrderTracePhaseSupport(
                    phase=phase,
                    eligible_window_count=coerce_count(row.get("eligible_window_count")),
                    matched_window_count=coerce_count(row.get("matched_window_count")),
                    support_ratio=optional_float(row.get("support_ratio")) or 0.0,
                )
            )
        return tuple(rows)

    def _order_harmonic_summaries(
        self,
        raw_summaries: object,
    ) -> tuple[ReportOrderHarmonicEvidenceSummary, ...]:
        if not isinstance(raw_summaries, list):
            return ()
        summaries: list[ReportOrderHarmonicEvidenceSummary] = []
        for row in raw_summaries:
            if not isinstance(row, Mapping):
                continue
            order_label = text_or_none(row.get("order_label"))
            if order_label is None:
                continue
            summaries.append(
                ReportOrderHarmonicEvidenceSummary(
                    harmonic=coerce_count(row.get("harmonic")),
                    order_label=order_label,
                    eligible_window_count=coerce_count(row.get("eligible_window_count")),
                    matched_window_count=coerce_count(row.get("matched_window_count")),
                    support_ratio=optional_float(row.get("support_ratio")) or 0.0,
                    reference_coverage_ratio=optional_float(row.get("reference_coverage_ratio"))
                    or 0.0,
                    contiguous_support_ratio=optional_float(row.get("contiguous_support_ratio"))
                    or 0.0,
                    lock_score=optional_float(row.get("lock_score")) or 0.0,
                    mean_relative_error=optional_float(row.get("mean_relative_error")),
                    relative_error_stddev=optional_float(row.get("relative_error_stddev")),
                    drift_score=optional_float(row.get("drift_score")) or 0.0,
                    peak_intensity_db=optional_float(row.get("peak_intensity_db")),
                    mean_vibration_strength_db=optional_float(
                        row.get("mean_vibration_strength_db")
                    ),
                )
            )
        return tuple(summaries)

    def _order_ref_sources(self, raw_sources: object) -> tuple[str, ...]:
        if not isinstance(raw_sources, list):
            return ()
        return tuple(
            source
            for source in (text_or_none(raw_source) for raw_source in raw_sources)
            if source is not None
        )

    def _optional_count(self, raw_value: object) -> int | None:
        if raw_value is None or isinstance(raw_value, bool):
            return None
        try:
            return coerce_count(raw_value)
        except (TypeError, ValueError):
            return None

    def _spatial_location_summaries(
        self,
        raw_summaries: object,
    ) -> tuple[ReportSpatialLocationSummary, ...]:
        if not isinstance(raw_summaries, list):
            return ()
        summaries: list[ReportSpatialLocationSummary] = []
        for row in raw_summaries:
            if not isinstance(row, Mapping):
                continue
            location = text_or_none(row.get("location"))
            if location is None:
                continue
            summaries.append(
                ReportSpatialLocationSummary(
                    location=location,
                    sensor_ids=self._text_tuple(row.get("sensor_ids")),
                    supporting_window_count=coerce_count(row.get("supporting_window_count")),
                    support_ratio=optional_float(row.get("support_ratio")) or 0.0,
                    coherent_window_count=coerce_count(row.get("coherent_window_count")),
                    coherence_ratio=optional_float(row.get("coherence_ratio")),
                    peak_intensity_db=optional_float(row.get("peak_intensity_db")),
                    mean_vibration_strength_db=optional_float(
                        row.get("mean_vibration_strength_db")
                    ),
                )
            )
        return tuple(summaries)

    def _text_tuple(self, raw_values: object) -> tuple[str, ...]:
        if not isinstance(raw_values, list):
            return ()
        return tuple(
            value
            for value in (text_or_none(raw_value) for raw_value in raw_values)
            if value is not None
        )

    def _proof_basis(self, raw_value: object) -> LocationProofBasis | None:
        value = text_or_none(raw_value)
        if value not in {
            "whole_run_summary",
            "supporting_windows_raw_backed",
            "supporting_windows_summary_only",
        }:
            return None
        return cast(LocationProofBasis, value)


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
