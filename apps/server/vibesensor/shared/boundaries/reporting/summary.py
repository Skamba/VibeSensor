"""Canonical reporting summary boundary for history and PDF preparation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from vibesensor.domain import LocationIntensitySummary
from vibesensor.domain.diagnosis_assessment import LEGACY_CONTEXT_CAVEAT_KEY
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
from vibesensor.shared.types.history_analysis_contracts import (
    DIAGNOSIS_DATA_QUALITY_LIMITATION_VALUES,
    DiagnosisDataQualityLimitation,
    DiagnosisExemplarKind,
    DiagnosisFactorKey,
    DiagnosisFactorPolarity,
    DiagnosisFactorSeverity,
    LocationProofBasis,
    WholeRunDiagnosisDataBasis,
)
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "NormalizedReportSummary",
    "ReportDiagnosisExemplarReference",
    "ReportDiagnosisDataQualitySummary",
    "ReportDiagnosisFactor",
    "ReportDiagnosisFactorDetails",
    "ReportOrderHarmonicEvidenceSummary",
    "ReportOrderTracePhaseSupport",
    "ReportOrderTraceSupportInterval",
    "ReportSpatialLocationSummary",
    "ReportWholeRunContextInterval",
    "ReportWholeRunDiagnosisSummary",
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
    usable_window_count: int
    limited_window_count: int
    excluded_window_count: int
    shock_transient_window_count: int
    sensor_clipping_window_count: int
    sensor_mounting_artifact_window_count: int
    sensor_timing_integrity_window_count: int
    speed_context_limited_window_count: int
    mean_quality_score: float | None
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
class ReportDiagnosisExemplarReference:
    """Typed persisted exemplar reference for one fused whole-run diagnosis."""

    kind: DiagnosisExemplarKind
    order_hypothesis_key: str | None
    support_interval_index: int | None
    spatial_candidate_key: str | None
    context_segment_index: int | None
    location: str | None
    phase: str | None
    speed_band: str | None


@dataclass(frozen=True, slots=True)
class ReportDiagnosisFactorDetails:
    """Typed structured details for one persisted diagnosis factor row."""

    raw_backed_sample_count: int | None
    supporting_window_count: int | None
    supporting_duration_s: float | None
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    frequency_span_hz: float | None
    supporting_location_count: int | None
    top_support_location: str | None
    top_support_share: float | None
    mean_relative_error: float | None
    snr_db: float | None
    alternative_source: str | None
    speed_gap_window_count: int | None
    rpm_gap_window_count: int | None
    fallback_reason: str | None
    car_data_reference_scope: str | None
    car_data_confidence: str | None


@dataclass(frozen=True, slots=True)
class ReportDiagnosisFactor:
    """Typed support or counterevidence factor for one fused diagnosis."""

    factor_key: DiagnosisFactorKey
    polarity: DiagnosisFactorPolarity
    severity: DiagnosisFactorSeverity
    weight: float
    details: ReportDiagnosisFactorDetails


@dataclass(frozen=True, slots=True)
class ReportDiagnosisDataQualitySummary:
    """Typed persisted data-quality summary for report/history reload paths."""

    usable_window_count: int | None
    limited_window_count: int | None
    excluded_window_count: int | None
    mean_quality_score: float | None
    speed_context_limited_window_count: int
    sensor_timing_integrity_window_count: int
    sensor_mounting_artifact_window_count: int
    sensor_clipping_window_count: int
    shock_transient_window_count: int
    limitation_keys: tuple[DiagnosisDataQualityLimitation, ...]


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
class ReportWholeRunDiagnosisSummary:
    """Typed persisted fused diagnosis summary for report/history reload paths."""

    diagnosis_key: str
    suspected_source: str
    rank: int
    data_basis: WholeRunDiagnosisDataBasis
    support_score: float | None
    counterevidence_score: float | None
    total_score: float | None
    order_hypothesis_key: str | None
    spatial_candidate_key: str | None
    location_proof_basis: LocationProofBasis | None
    supporting_window_count: int | None
    supporting_duration_s: float | None
    supporting_sensor_count: int | None
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    dominant_location: str | None
    runner_up_location: str | None
    dominant_phase: str | None
    dominant_speed_band: str | None
    location_separation_db: float | None
    dominance_ratio: float | None
    alternative_source: str | None
    confidence_gap_to_alternative: float | None
    ambiguous_diagnosis: bool
    ambiguous_location: bool
    suspicious: bool
    weak_spatial_separation: bool
    has_reference_gap: bool
    uses_summary_fallback: bool
    fallback_reason: str | None
    data_quality_summary: ReportDiagnosisDataQualitySummary
    exemplar_references: tuple[ReportDiagnosisExemplarReference, ...]
    support_factors: tuple[ReportDiagnosisFactor, ...]
    counterevidence_factors: tuple[ReportDiagnosisFactor, ...]


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
    whole_run_diagnosis_summaries: tuple[ReportWholeRunDiagnosisSummary, ...]


@dataclass(frozen=True, slots=True)
class _FieldDecoder:
    name: str
    read: Callable[[Mapping[str, object]], object]


@dataclass(frozen=True, slots=True)
class _RowDecoder[RowModelT]:
    factory: Callable[..., RowModelT]
    fields: tuple[_FieldDecoder, ...]
    required_fields: frozenset[str] = frozenset()


def _field(name: str, read: Callable[[Mapping[str, object]], object]) -> _FieldDecoder:
    return _FieldDecoder(name=name, read=read)


def _payload_field(name: str, read: Callable[[object], object]) -> _FieldDecoder:
    def read_field(row: Mapping[str, object]) -> object:
        return read(row.get(name))

    return _field(name, read_field)


def _text_field(name: str) -> _FieldDecoder:
    return _payload_field(name, text_or_none)


def _float_field(name: str) -> _FieldDecoder:
    return _payload_field(name, optional_float)


def _float_or_field(name: str, default: float = 0.0) -> _FieldDecoder:
    def read_float_or(raw: object) -> object:
        return optional_float(raw) or default

    return _payload_field(name, read_float_or)


def _count_field(name: str) -> _FieldDecoder:
    return _payload_field(name, coerce_count)


def _optional_count(raw_value: object) -> int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        return coerce_count(raw_value)
    except (TypeError, ValueError):
        return None


def _optional_count_field(name: str) -> _FieldDecoder:
    return _payload_field(name, _optional_count)


def _bool_field(name: str) -> _FieldDecoder:
    return _payload_field(name, bool)


def _text_tuple(raw_values: object) -> tuple[str, ...]:
    if not isinstance(raw_values, list):
        return ()
    return tuple(
        value
        for value in (text_or_none(raw_value) for raw_value in raw_values)
        if value is not None
    )


def _text_tuple_field(name: str) -> _FieldDecoder:
    return _payload_field(name, _text_tuple)


def _data_quality_limitations(raw_values: object) -> tuple[DiagnosisDataQualityLimitation, ...]:
    if not isinstance(raw_values, list):
        return ()
    limitations: list[DiagnosisDataQualityLimitation] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        limitation = _literal_text_or_none(raw_value, DIAGNOSIS_DATA_QUALITY_LIMITATION_VALUES)
        if limitation is not None and limitation not in seen:
            limitations.append(limitation)
            seen.add(limitation)
    return tuple(limitations)


def _literal_text_or_none[LiteralTextT: str](
    raw_value: object,
    allowed: frozenset[LiteralTextT],
) -> LiteralTextT | None:
    value = text_or_none(raw_value)
    if value is None or value not in allowed:
        return None
    return value


def _enum_field[LiteralTextT: str](
    name: str,
    allowed: frozenset[LiteralTextT],
) -> _FieldDecoder:
    def read_enum(raw: object) -> object:
        return _literal_text_or_none(raw, allowed)

    return _payload_field(name, read_enum)


def _decode_row[RowModelT](
    raw: object,
    decoder: _RowDecoder[RowModelT],
) -> RowModelT | None:
    if not isinstance(raw, Mapping):
        return None
    values = {field.name: field.read(raw) for field in decoder.fields}
    if any(values[name] is None for name in decoder.required_fields):
        return None
    return decoder.factory(**values)


def _decode_rows[RowModelT](
    raw_rows: object,
    decoder: _RowDecoder[RowModelT],
) -> tuple[RowModelT, ...]:
    if not isinstance(raw_rows, list):
        return ()
    return tuple(decoded for row in raw_rows if (decoded := _decode_row(row, decoder)) is not None)


def _rows_field[RowModelT](
    name: str,
    decoder: _RowDecoder[RowModelT],
) -> _FieldDecoder:
    def read_rows(raw: object) -> object:
        return _decode_rows(raw, decoder)

    return _payload_field(name, read_rows)


def _row_field[RowModelT](
    name: str,
    decoder: _RowDecoder[RowModelT],
    default: RowModelT,
) -> _FieldDecoder:
    def read_row(raw: object) -> object:
        return _decode_row(raw, decoder) or default

    return _payload_field(name, read_row)


_PROOF_BASIS_VALUES: frozenset[LocationProofBasis] = frozenset(
    {
        "whole_run_summary",
        "supporting_windows_raw_backed",
        "supporting_windows_summary_only",
    }
)
_DIAGNOSIS_EXEMPLAR_KIND_VALUES: frozenset[DiagnosisExemplarKind] = frozenset(
    {
        "order_support_interval",
        "whole_run_context_interval",
        "spatial_location",
    }
)
_DIAGNOSIS_DATA_BASIS_VALUES: frozenset[WholeRunDiagnosisDataBasis] = frozenset(
    {"raw_backed", "partial_raw_backed", "summary_only"}
)
_DIAGNOSIS_FACTOR_KEY_VALUES: frozenset[DiagnosisFactorKey] = frozenset(
    {
        "raw_backed",
        "repeated_support",
        "sustained_support",
        "stable_frequency",
        "tight_order_lock",
        "localized_support",
        "clean_signal",
        "summary_only",
        "raw_replay_incomplete",
        LEGACY_CONTEXT_CAVEAT_KEY,
        "speed_context_gaps",
        "rpm_context_gaps",
        "sparse_support",
        "brief_support",
        "drifting_frequency",
        "loose_order_lock",
        "mixed_support_locations",
        "noisy_signal",
        "weak_spatial",
        "close_alternative",
        "incomplete_reference",
    }
)
_DIAGNOSIS_FACTOR_POLARITY_VALUES: frozenset[DiagnosisFactorPolarity] = frozenset(
    {"support", "counterevidence"}
)
_DIAGNOSIS_FACTOR_SEVERITY_VALUES: frozenset[DiagnosisFactorSeverity] = frozenset(
    {"low", "medium", "high"}
)

_TIMELINE_INTERVAL_DECODER = _RowDecoder(
    factory=ReportTimelineInterval,
    fields=(
        _text_field("phase"),
        _float_field("start_t_s"),
        _float_field("end_t_s"),
        _float_field("speed_min_kmh"),
        _float_field("speed_max_kmh"),
        _bool_field("has_fault_evidence"),
    ),
    required_fields=frozenset({"phase"}),
)
_WHOLE_RUN_CONTEXT_INTERVAL_DECODER = _RowDecoder(
    factory=ReportWholeRunContextInterval,
    fields=(
        _count_field("segment_index"),
        _text_field("phase"),
        _text_field("load_state"),
        _count_field("start_window_index"),
        _count_field("end_window_index"),
        _float_field("start_t_s"),
        _float_field("end_t_s"),
        _float_field("speed_min_kmh"),
        _float_field("speed_max_kmh"),
        _text_field("speed_band"),
        _count_field("full_context_window_count"),
        _count_field("partial_context_window_count"),
        _count_field("missing_context_window_count"),
    ),
    required_fields=frozenset({"phase", "load_state"}),
)
_ORDER_SUPPORT_INTERVAL_DECODER = _RowDecoder(
    factory=ReportOrderTraceSupportInterval,
    fields=(
        _count_field("interval_index"),
        _count_field("start_window_index"),
        _count_field("end_window_index"),
        _count_field("matched_window_count"),
        _float_or_field("support_ratio"),
        _float_field("start_t_s"),
        _float_field("end_t_s"),
        _text_field("phase"),
        _text_field("load_state"),
        _text_field("speed_band"),
        _float_field("mean_relative_error"),
    ),
)
_ORDER_PHASE_SUPPORT_DECODER = _RowDecoder(
    factory=ReportOrderTracePhaseSupport,
    fields=(
        _text_field("phase"),
        _count_field("eligible_window_count"),
        _count_field("matched_window_count"),
        _float_or_field("support_ratio"),
    ),
    required_fields=frozenset({"phase"}),
)
_ORDER_HARMONIC_SUMMARY_DECODER = _RowDecoder(
    factory=ReportOrderHarmonicEvidenceSummary,
    fields=(
        _count_field("harmonic"),
        _text_field("order_label"),
        _count_field("eligible_window_count"),
        _count_field("matched_window_count"),
        _float_or_field("support_ratio"),
        _float_or_field("reference_coverage_ratio"),
        _float_or_field("contiguous_support_ratio"),
        _float_or_field("lock_score"),
        _float_field("mean_relative_error"),
        _float_field("relative_error_stddev"),
        _float_or_field("drift_score"),
        _float_field("peak_intensity_db"),
        _float_field("mean_vibration_strength_db"),
    ),
    required_fields=frozenset({"order_label"}),
)
_SPATIAL_LOCATION_SUMMARY_DECODER = _RowDecoder(
    factory=ReportSpatialLocationSummary,
    fields=(
        _text_field("location"),
        _text_tuple_field("sensor_ids"),
        _count_field("supporting_window_count"),
        _float_or_field("support_ratio"),
        _count_field("coherent_window_count"),
        _float_field("coherence_ratio"),
        _float_field("peak_intensity_db"),
        _float_field("mean_vibration_strength_db"),
    ),
    required_fields=frozenset({"location"}),
)
_DIAGNOSIS_EXEMPLAR_REFERENCE_DECODER = _RowDecoder(
    factory=ReportDiagnosisExemplarReference,
    fields=(
        _enum_field("kind", _DIAGNOSIS_EXEMPLAR_KIND_VALUES),
        _text_field("order_hypothesis_key"),
        _optional_count_field("support_interval_index"),
        _text_field("spatial_candidate_key"),
        _optional_count_field("context_segment_index"),
        _text_field("location"),
        _text_field("phase"),
        _text_field("speed_band"),
    ),
    required_fields=frozenset({"kind"}),
)
_DIAGNOSIS_FACTOR_DETAILS_DECODER = _RowDecoder(
    factory=ReportDiagnosisFactorDetails,
    fields=(
        _optional_count_field("raw_backed_sample_count"),
        _optional_count_field("supporting_window_count"),
        _float_field("supporting_duration_s"),
        _float_field("stable_frequency_min_hz"),
        _float_field("stable_frequency_max_hz"),
        _float_field("frequency_span_hz"),
        _optional_count_field("supporting_location_count"),
        _text_field("top_support_location"),
        _float_field("top_support_share"),
        _float_field("mean_relative_error"),
        _float_field("snr_db"),
        _text_field("alternative_source"),
        _optional_count_field("speed_gap_window_count"),
        _optional_count_field("rpm_gap_window_count"),
        _text_field("fallback_reason"),
        _text_field("car_data_reference_scope"),
        _text_field("car_data_confidence"),
    ),
)
_EMPTY_DIAGNOSIS_FACTOR_DETAILS = ReportDiagnosisFactorDetails(
    raw_backed_sample_count=None,
    supporting_window_count=None,
    supporting_duration_s=None,
    stable_frequency_min_hz=None,
    stable_frequency_max_hz=None,
    frequency_span_hz=None,
    supporting_location_count=None,
    top_support_location=None,
    top_support_share=None,
    mean_relative_error=None,
    snr_db=None,
    alternative_source=None,
    speed_gap_window_count=None,
    rpm_gap_window_count=None,
    fallback_reason=None,
    car_data_reference_scope=None,
    car_data_confidence=None,
)


def _diagnosis_factor_details_from_mapping(raw_details: object) -> ReportDiagnosisFactorDetails:
    details = _decode_row(
        raw_details if isinstance(raw_details, Mapping) else {},
        _DIAGNOSIS_FACTOR_DETAILS_DECODER,
    )
    return details if details is not None else _EMPTY_DIAGNOSIS_FACTOR_DETAILS


_DIAGNOSIS_FACTOR_DECODER = _RowDecoder(
    factory=ReportDiagnosisFactor,
    fields=(
        _enum_field("factor_key", _DIAGNOSIS_FACTOR_KEY_VALUES),
        _enum_field("polarity", _DIAGNOSIS_FACTOR_POLARITY_VALUES),
        _enum_field("severity", _DIAGNOSIS_FACTOR_SEVERITY_VALUES),
        _float_or_field("weight"),
        _payload_field("details", _diagnosis_factor_details_from_mapping),
    ),
    required_fields=frozenset({"factor_key", "polarity", "severity"}),
)
_DIAGNOSIS_DATA_QUALITY_DECODER = _RowDecoder(
    factory=ReportDiagnosisDataQualitySummary,
    fields=(
        _optional_count_field("usable_window_count"),
        _optional_count_field("limited_window_count"),
        _optional_count_field("excluded_window_count"),
        _float_field("mean_quality_score"),
        _count_field("speed_context_limited_window_count"),
        _count_field("sensor_timing_integrity_window_count"),
        _count_field("sensor_mounting_artifact_window_count"),
        _count_field("sensor_clipping_window_count"),
        _count_field("shock_transient_window_count"),
        _payload_field("limitation_keys", _data_quality_limitations),
    ),
)
_EMPTY_DIAGNOSIS_DATA_QUALITY = ReportDiagnosisDataQualitySummary(
    usable_window_count=None,
    limited_window_count=None,
    excluded_window_count=None,
    mean_quality_score=None,
    speed_context_limited_window_count=0,
    sensor_timing_integrity_window_count=0,
    sensor_mounting_artifact_window_count=0,
    sensor_clipping_window_count=0,
    shock_transient_window_count=0,
    limitation_keys=(),
)
_WHOLE_RUN_ORDER_SUMMARY_DECODER = _RowDecoder(
    factory=ReportWholeRunOrderSummary,
    fields=(
        _text_field("hypothesis_key"),
        _text_field("suspected_source"),
        _text_field("order_family"),
        _text_field("order_label"),
        _count_field("total_window_count"),
        _count_field("eligible_window_count"),
        _count_field("matched_window_count"),
        _float_or_field("support_ratio"),
        _float_or_field("reference_coverage_ratio"),
        _count_field("longest_contiguous_support_window_count"),
        _float_or_field("contiguous_support_ratio"),
        _count_field("usable_window_count"),
        _count_field("limited_window_count"),
        _count_field("excluded_window_count"),
        _count_field("shock_transient_window_count"),
        _count_field("sensor_clipping_window_count"),
        _count_field("sensor_mounting_artifact_window_count"),
        _count_field("sensor_timing_integrity_window_count"),
        _count_field("speed_context_limited_window_count"),
        _float_field("mean_quality_score"),
        _rows_field("support_intervals", _ORDER_SUPPORT_INTERVAL_DECODER),
        _rows_field("phase_support", _ORDER_PHASE_SUPPORT_DECODER),
        _rows_field("harmonic_summaries", _ORDER_HARMONIC_SUMMARY_DECODER),
        _float_field("stable_frequency_min_hz"),
        _float_field("stable_frequency_max_hz"),
        _optional_count_field("exemplar_interval_index"),
        _text_field("dominant_phase"),
        _text_field("dominant_speed_band"),
        _text_field("strongest_location"),
        _float_field("mean_relative_error"),
        _float_field("relative_error_stddev"),
        _float_or_field("drift_score"),
        _float_or_field("lock_score"),
        _float_field("peak_intensity_db"),
        _float_field("mean_vibration_strength_db"),
        _text_tuple_field("ref_sources"),
    ),
    required_fields=frozenset(
        {"hypothesis_key", "suspected_source", "order_family", "order_label"}
    ),
)
_WHOLE_RUN_SPATIAL_SUMMARY_DECODER = _RowDecoder(
    factory=ReportWholeRunSpatialSummary,
    fields=(
        _text_field("candidate_key"),
        _text_field("suspected_source"),
        _enum_field("proof_basis", _PROOF_BASIS_VALUES),
        _count_field("total_window_count"),
        _count_field("supporting_window_count"),
        _count_field("supporting_sensor_count"),
        _count_field("coherent_window_count"),
        _float_field("coherence_ratio"),
        _text_field("dominant_location"),
        _text_field("runner_up_location"),
        _float_field("location_separation_db"),
        _float_field("dominance_ratio"),
        _bool_field("ambiguous_location"),
        _bool_field("weak_spatial_separation"),
        _rows_field("location_summaries", _SPATIAL_LOCATION_SUMMARY_DECODER),
    ),
    required_fields=frozenset({"candidate_key", "suspected_source", "proof_basis"}),
)
_WHOLE_RUN_DIAGNOSIS_SUMMARY_DECODER = _RowDecoder(
    factory=ReportWholeRunDiagnosisSummary,
    fields=(
        _text_field("diagnosis_key"),
        _text_field("suspected_source"),
        _count_field("rank"),
        _enum_field("data_basis", _DIAGNOSIS_DATA_BASIS_VALUES),
        _float_field("support_score"),
        _float_field("counterevidence_score"),
        _float_field("total_score"),
        _text_field("order_hypothesis_key"),
        _text_field("spatial_candidate_key"),
        _enum_field("location_proof_basis", _PROOF_BASIS_VALUES),
        _optional_count_field("supporting_window_count"),
        _float_field("supporting_duration_s"),
        _optional_count_field("supporting_sensor_count"),
        _float_field("stable_frequency_min_hz"),
        _float_field("stable_frequency_max_hz"),
        _text_field("dominant_location"),
        _text_field("runner_up_location"),
        _text_field("dominant_phase"),
        _text_field("dominant_speed_band"),
        _float_field("location_separation_db"),
        _float_field("dominance_ratio"),
        _text_field("alternative_source"),
        _float_field("confidence_gap_to_alternative"),
        _bool_field("ambiguous_diagnosis"),
        _bool_field("ambiguous_location"),
        _bool_field("suspicious"),
        _bool_field("weak_spatial_separation"),
        _bool_field("has_reference_gap"),
        _bool_field("uses_summary_fallback"),
        _text_field("fallback_reason"),
        _row_field(
            "data_quality_summary",
            _DIAGNOSIS_DATA_QUALITY_DECODER,
            _EMPTY_DIAGNOSIS_DATA_QUALITY,
        ),
        _rows_field("exemplar_references", _DIAGNOSIS_EXEMPLAR_REFERENCE_DECODER),
        _rows_field("support_factors", _DIAGNOSIS_FACTOR_DECODER),
        _rows_field("counterevidence_factors", _DIAGNOSIS_FACTOR_DECODER),
    ),
    required_fields=frozenset({"diagnosis_key", "suspected_source", "data_basis"}),
)


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
            timeline_intervals=_decode_rows(
                self._payload.get("phase_timeline"),
                _TIMELINE_INTERVAL_DECODER,
            ),
            whole_run_context_intervals=_decode_rows(
                self._payload.get("whole_run_context_intervals"),
                _WHOLE_RUN_CONTEXT_INTERVAL_DECODER,
            ),
            whole_run_order_summaries=_decode_rows(
                self._payload.get("whole_run_order_summaries"),
                _WHOLE_RUN_ORDER_SUMMARY_DECODER,
            ),
            whole_run_spatial_summaries=_decode_rows(
                self._payload.get("whole_run_spatial_summaries"),
                _WHOLE_RUN_SPATIAL_SUMMARY_DECODER,
            ),
            whole_run_diagnosis_summaries=_decode_rows(
                self._payload.get("whole_run_diagnosis_summaries"),
                _WHOLE_RUN_DIAGNOSIS_SUMMARY_DECODER,
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
