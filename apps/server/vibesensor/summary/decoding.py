"""Canonical reporting summary boundary for history and PDF preparation.

Persisted whole-run summaries are decoded straight into their canonical
``shared.types`` dataclasses. Report/history reload stays tolerant of legacy or
partial payloads: :func:`lenient_row` coerces each field from the dataclass
type hints and drops rows that lack required identity fields or fail the
dataclass validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields, is_dataclass
from enum import Enum
from functools import cache
from types import UnionType
from typing import (
    Literal,
    TypeAliasType,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from vibesensor.common.scalars import (
    coerce_count,
    optional_float,
    text_or_none,
)
from vibesensor.domain.location_hotspot import LocationIntensitySummary
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.summary.analysis_views import PeakTableRow
from vibesensor.summary.hotspot_fields import (
    location_intensity_summaries_from_rows,
)
from vibesensor.summary.order_trace_contracts import OrderTraceSummary
from vibesensor.summary.spatial_evidence_contracts import SpatialEvidenceSummary
from vibesensor.summary.whole_run_analysis import WholeRunContextInterval
from vibesensor.summary.whole_run_diagnosis_contracts import (
    WholeRunDiagnosisSummary,
)

__all__ = [
    "NormalizedReportSummary",
    "ReportSummaryNormalizer",
    "ReportTimelineInterval",
    "has_projectable_report_payload",
    "lenient_row",
    "lenient_rows",
    "report_diagnosis_summaries",
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
    whole_run_context_intervals: tuple[WholeRunContextInterval, ...]
    whole_run_order_summaries: tuple[OrderTraceSummary, ...]
    whole_run_spatial_summaries: tuple[SpatialEvidenceSummary, ...]
    whole_run_diagnosis_summaries: tuple[WholeRunDiagnosisSummary, ...]


# ---------------------------------------------------------------------------
# Tolerant row decoding driven by the canonical dataclass type hints
# ---------------------------------------------------------------------------


type _FieldSpec = tuple[str, object, bool, object]


@cache
def _row_field_specs(cls: type) -> tuple[_FieldSpec, ...]:
    hints = get_type_hints(cls)
    specs: list[_FieldSpec] = []
    for field in fields(cls):
        field_type, optional = _optional_inner(hints[field.name])
        default: object = MISSING
        if field.default is not MISSING:
            default = field.default
        elif field.default_factory is not MISSING:
            default = field.default_factory()
        specs.append((field.name, field_type, optional, default))
    return tuple(specs)


def _unalias(tp: object) -> object:
    while isinstance(tp, TypeAliasType):
        tp = tp.__value__
    return tp


def _optional_inner(tp: object) -> tuple[object, bool]:
    tp = _unalias(tp)
    if get_origin(tp) in (Union, UnionType):
        args = get_args(tp)
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1 and len(args) == 2:
            return _unalias(non_none[0]), True
    return tp, False


def _optional_count(raw_value: object) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    return coerce_count(raw_value)


def _lenient_tuple(item_type: object, raw_value: object) -> tuple[object, ...]:
    if not isinstance(raw_value, list):
        return ()
    if isinstance(item_type, type) and is_dataclass(item_type):
        return lenient_rows(item_type, raw_value)
    if get_origin(item_type) is Literal:
        allowed = get_args(item_type)
        unique: list[str] = []
        for raw_item in raw_value:
            item = text_or_none(raw_item)
            if item is not None and item in allowed and item not in unique:
                unique.append(item)
        return tuple(unique)
    return tuple(
        value for value in (text_or_none(raw_item) for raw_item in raw_value) if value is not None
    )


def _lenient_value(field_type: object, raw_value: object, *, optional: bool) -> object:
    if field_type is str:
        return text_or_none(raw_value)
    if field_type is bool:
        return bool(raw_value)
    if field_type is int:
        return _optional_count(raw_value) if optional else coerce_count(raw_value)
    if field_type is float:
        value = optional_float(raw_value)
        return value if optional else (value or 0.0)
    if get_origin(field_type) is Literal:
        text = text_or_none(raw_value)
        return text if text in get_args(field_type) else None
    if get_origin(field_type) is tuple:
        return _lenient_tuple(_unalias(get_args(field_type)[0]), raw_value)
    if isinstance(field_type, type) and issubclass(field_type, Enum):
        text = text_or_none(raw_value)
        try:
            return field_type(text) if text is not None else None
        except ValueError:
            return None
    if isinstance(field_type, type) and is_dataclass(field_type):
        return lenient_row(field_type, raw_value)
    raise TypeError(f"unsupported report summary field type {field_type!r}")


def lenient_row[RowT](cls: type[RowT], raw: object) -> RowT | None:
    """Tolerantly decode one persisted summary row into its canonical dataclass.

    Scalars are coerced (missing counts and required ratios default to ``0``,
    invalid optional values become ``None``, booleans use truthiness, unknown
    enum values are discarded). Nested rows are decoded the same way and
    invalid ones are dropped. The row itself is dropped (``None``) when a
    required text/enum field is missing or the dataclass rejects the values.
    """
    if not isinstance(raw, Mapping):
        return None
    values: dict[str, object] = {}
    for name, field_type, optional, default in _row_field_specs(cast(type, cls)):
        value = _lenient_value(field_type, raw.get(name), optional=optional)
        if value is None and not optional:
            if default is MISSING or not is_dataclass(field_type):
                return None
            value = default
        values[name] = value
    try:
        return cls(**values)
    except ValueError:
        return None


def lenient_rows[RowT](cls: type[RowT], raw_rows: object) -> tuple[RowT, ...]:
    """Tolerantly decode a persisted list of summary rows, dropping invalid rows."""
    if not isinstance(raw_rows, list):
        return ()
    return tuple(row for raw in raw_rows if (row := lenient_row(cls, raw)) is not None)


def report_diagnosis_summaries(raw_rows: object) -> tuple[WholeRunDiagnosisSummary, ...]:
    """Tolerantly decode persisted whole-run diagnosis summaries for report/history use."""
    return lenient_rows(WholeRunDiagnosisSummary, raw_rows)


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
            timeline_intervals=lenient_rows(
                ReportTimelineInterval,
                self._payload.get("phase_timeline"),
            ),
            whole_run_context_intervals=lenient_rows(
                WholeRunContextInterval,
                self._payload.get("whole_run_context_intervals"),
            ),
            whole_run_order_summaries=lenient_rows(
                OrderTraceSummary,
                self._payload.get("whole_run_order_summaries"),
            ),
            whole_run_spatial_summaries=lenient_rows(
                SpatialEvidenceSummary,
                self._payload.get("whole_run_spatial_summaries"),
            ),
            whole_run_diagnosis_summaries=report_diagnosis_summaries(
                self._payload.get("whole_run_diagnosis_summaries"),
            ),
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
