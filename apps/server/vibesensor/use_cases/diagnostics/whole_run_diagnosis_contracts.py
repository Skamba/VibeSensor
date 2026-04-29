"""Whole-run fused diagnosis contracts for persisted summaries and exemplars.

These compact contracts sit above the whole-run context, order, and spatial
summary layers. They intentionally define the diagnosis shell, ambiguity flags,
fallback markers, and exemplar references before later issues settle the stable
support/counterevidence factor vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from vibesensor.shared.types.history_analysis_contracts import (
    DiagnosisExemplarKind,
    DiagnosisFactorKey,
    DiagnosisFactorPolarity,
    DiagnosisFactorSeverity,
    LocationProofBasis,
    WholeRunDiagnosisDataBasis,
)
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.whole_run_json_helpers import (
    non_empty_text_or_none as _non_empty_text_or_none,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    optional_float_or_none as _optional_float_or_none,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    optional_int_or_none as _optional_int_or_none,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    required_bool_field as _required_bool_field,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    required_float_field as _required_float_field,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    required_int_field as _required_int_field,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    set_optional_value as _set_optional,
)

__all__ = [
    "DiagnosisExemplarReference",
    "DiagnosisFactor",
    "DiagnosisFactorDetails",
    "WholeRunDiagnosisSummary",
]


@dataclass(frozen=True, slots=True)
class DiagnosisExemplarReference:
    """Compact reference to one persisted exemplar for a fused diagnosis."""

    kind: DiagnosisExemplarKind
    order_hypothesis_key: str | None = None
    support_interval_index: int | None = None
    spatial_candidate_key: str | None = None
    context_segment_index: int | None = None
    location: str | None = None
    phase: str | None = None
    speed_band: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "order_support_interval":
            _require_text(self.order_hypothesis_key, field_name="order_hypothesis_key")
        elif self.kind == "whole_run_context_interval":
            if self.context_segment_index is None:
                raise ValueError("context_segment_index is required for whole_run_context_interval")
        elif self.kind == "spatial_location":
            _require_text(self.spatial_candidate_key, field_name="spatial_candidate_key")
            _require_text(self.location, field_name="location")
        if self.support_interval_index is not None:
            _require_nonnegative(self.support_interval_index, field_name="support_interval_index")
        if self.context_segment_index is not None:
            _require_nonnegative(self.context_segment_index, field_name="context_segment_index")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {"kind": self.kind}
        _set_optional(payload, "order_hypothesis_key", self.order_hypothesis_key)
        _set_optional(payload, "support_interval_index", self.support_interval_index)
        _set_optional(payload, "spatial_candidate_key", self.spatial_candidate_key)
        _set_optional(payload, "context_segment_index", self.context_segment_index)
        _set_optional(payload, "location", self.location)
        _set_optional(payload, "phase", self.phase)
        _set_optional(payload, "speed_band", self.speed_band)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> DiagnosisExemplarReference:
        return cls(
            kind=_required_exemplar_kind(data.get("kind")),
            order_hypothesis_key=_optional_text(data.get("order_hypothesis_key")),
            support_interval_index=_optional_int(data.get("support_interval_index")),
            spatial_candidate_key=_optional_text(data.get("spatial_candidate_key")),
            context_segment_index=_optional_int(data.get("context_segment_index")),
            location=_optional_text(data.get("location")),
            phase=_optional_text(data.get("phase")),
            speed_band=_optional_text(data.get("speed_band")),
        )


@dataclass(frozen=True, slots=True)
class DiagnosisFactorDetails:
    """Structured details carried by one persisted diagnosis factor row."""

    raw_backed_sample_count: int | None = None
    supporting_window_count: int | None = None
    supporting_duration_s: float | None = None
    stable_frequency_min_hz: float | None = None
    stable_frequency_max_hz: float | None = None
    frequency_span_hz: float | None = None
    supporting_location_count: int | None = None
    top_support_location: str | None = None
    top_support_share: float | None = None
    mean_relative_error: float | None = None
    snr_db: float | None = None
    alternative_source: str | None = None
    speed_gap_window_count: int | None = None
    rpm_gap_window_count: int | None = None
    fallback_reason: str | None = None
    car_data_reference_scope: str | None = None
    car_data_confidence: str | None = None

    def __post_init__(self) -> None:
        if self.raw_backed_sample_count is not None:
            _require_nonnegative(self.raw_backed_sample_count, field_name="raw_backed_sample_count")
        if self.supporting_window_count is not None:
            _require_nonnegative(self.supporting_window_count, field_name="supporting_window_count")
        if self.supporting_location_count is not None:
            _require_nonnegative(
                self.supporting_location_count,
                field_name="supporting_location_count",
            )
        if self.speed_gap_window_count is not None:
            _require_nonnegative(self.speed_gap_window_count, field_name="speed_gap_window_count")
        if self.rpm_gap_window_count is not None:
            _require_nonnegative(self.rpm_gap_window_count, field_name="rpm_gap_window_count")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {}
        _set_optional(payload, "raw_backed_sample_count", self.raw_backed_sample_count)
        _set_optional(payload, "supporting_window_count", self.supporting_window_count)
        _set_optional(payload, "supporting_duration_s", self.supporting_duration_s)
        _set_optional(payload, "stable_frequency_min_hz", self.stable_frequency_min_hz)
        _set_optional(payload, "stable_frequency_max_hz", self.stable_frequency_max_hz)
        _set_optional(payload, "frequency_span_hz", self.frequency_span_hz)
        _set_optional(payload, "supporting_location_count", self.supporting_location_count)
        _set_optional(payload, "top_support_location", self.top_support_location)
        _set_optional(payload, "top_support_share", self.top_support_share)
        _set_optional(payload, "mean_relative_error", self.mean_relative_error)
        _set_optional(payload, "snr_db", self.snr_db)
        _set_optional(payload, "alternative_source", self.alternative_source)
        _set_optional(payload, "speed_gap_window_count", self.speed_gap_window_count)
        _set_optional(payload, "rpm_gap_window_count", self.rpm_gap_window_count)
        _set_optional(payload, "fallback_reason", self.fallback_reason)
        _set_optional(payload, "car_data_reference_scope", self.car_data_reference_scope)
        _set_optional(payload, "car_data_confidence", self.car_data_confidence)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> DiagnosisFactorDetails:
        return cls(
            raw_backed_sample_count=_optional_int(data.get("raw_backed_sample_count")),
            supporting_window_count=_optional_int(data.get("supporting_window_count")),
            supporting_duration_s=_optional_float(data.get("supporting_duration_s")),
            stable_frequency_min_hz=_optional_float(data.get("stable_frequency_min_hz")),
            stable_frequency_max_hz=_optional_float(data.get("stable_frequency_max_hz")),
            frequency_span_hz=_optional_float(data.get("frequency_span_hz")),
            supporting_location_count=_optional_int(data.get("supporting_location_count")),
            top_support_location=_optional_text(data.get("top_support_location")),
            top_support_share=_optional_float(data.get("top_support_share")),
            mean_relative_error=_optional_float(data.get("mean_relative_error")),
            snr_db=_optional_float(data.get("snr_db")),
            alternative_source=_optional_text(data.get("alternative_source")),
            speed_gap_window_count=_optional_int(data.get("speed_gap_window_count")),
            rpm_gap_window_count=_optional_int(data.get("rpm_gap_window_count")),
            fallback_reason=_optional_text(data.get("fallback_reason")),
            car_data_reference_scope=_optional_text(data.get("car_data_reference_scope")),
            car_data_confidence=_optional_text(data.get("car_data_confidence")),
        )


@dataclass(frozen=True, slots=True)
class DiagnosisFactor:
    """One stable support or counterevidence factor for a fused diagnosis."""

    factor_key: DiagnosisFactorKey
    polarity: DiagnosisFactorPolarity
    severity: DiagnosisFactorSeverity
    weight: float
    details: DiagnosisFactorDetails = DiagnosisFactorDetails()

    def __post_init__(self) -> None:
        _require_factor_key(self.factor_key)
        _require_factor_polarity(self.polarity)
        _require_factor_severity(self.severity)
        if self.weight < 0:
            raise ValueError("weight must be >= 0")

    def to_json_object(self) -> JsonObject:
        return {
            "factor_key": self.factor_key,
            "polarity": self.polarity,
            "severity": self.severity,
            "weight": self.weight,
            "details": self.details.to_json_object(),
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> DiagnosisFactor:
        raw_details = data.get("details")
        details = (
            DiagnosisFactorDetails.from_mapping(raw_details)
            if isinstance(raw_details, dict)
            else DiagnosisFactorDetails()
        )
        return cls(
            factor_key=_required_factor_key(data.get("factor_key")),
            polarity=_required_factor_polarity(data.get("polarity")),
            severity=_required_factor_severity(data.get("severity")),
            weight=_required_numeric(data, "weight"),
            details=details,
        )


@dataclass(frozen=True, slots=True)
class WholeRunDiagnosisSummary:
    """Compact persisted/report-facing summary for one fused whole-run diagnosis."""

    diagnosis_key: str
    suspected_source: str
    rank: int
    data_basis: WholeRunDiagnosisDataBasis
    support_score: float | None = None
    counterevidence_score: float | None = None
    total_score: float | None = None
    order_hypothesis_key: str | None = None
    spatial_candidate_key: str | None = None
    location_proof_basis: LocationProofBasis | None = None
    supporting_window_count: int | None = None
    supporting_duration_s: float | None = None
    supporting_sensor_count: int | None = None
    stable_frequency_min_hz: float | None = None
    stable_frequency_max_hz: float | None = None
    dominant_location: str | None = None
    runner_up_location: str | None = None
    dominant_phase: str | None = None
    dominant_speed_band: str | None = None
    location_separation_db: float | None = None
    dominance_ratio: float | None = None
    alternative_source: str | None = None
    confidence_gap_to_alternative: float | None = None
    ambiguous_diagnosis: bool = False
    ambiguous_location: bool = False
    suspicious: bool = False
    weak_spatial_separation: bool = False
    has_reference_gap: bool = False
    uses_summary_fallback: bool = False
    fallback_reason: str | None = None
    exemplar_references: tuple[DiagnosisExemplarReference, ...] = ()
    support_factors: tuple[DiagnosisFactor, ...] = ()
    counterevidence_factors: tuple[DiagnosisFactor, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.diagnosis_key, field_name="diagnosis_key")
        _require_text(self.suspected_source, field_name="suspected_source")
        _require_nonnegative(self.rank, field_name="rank")
        if self.supporting_window_count is not None:
            _require_nonnegative(self.supporting_window_count, field_name="supporting_window_count")
        if self.supporting_sensor_count is not None:
            _require_nonnegative(self.supporting_sensor_count, field_name="supporting_sensor_count")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "diagnosis_key": self.diagnosis_key,
            "suspected_source": self.suspected_source,
            "rank": self.rank,
            "data_basis": self.data_basis,
            "ambiguous_diagnosis": self.ambiguous_diagnosis,
            "ambiguous_location": self.ambiguous_location,
            "suspicious": self.suspicious,
            "weak_spatial_separation": self.weak_spatial_separation,
            "has_reference_gap": self.has_reference_gap,
            "uses_summary_fallback": self.uses_summary_fallback,
            "exemplar_references": [
                exemplar.to_json_object() for exemplar in self.exemplar_references
            ],
            "support_factors": [factor.to_json_object() for factor in self.support_factors],
            "counterevidence_factors": [
                factor.to_json_object() for factor in self.counterevidence_factors
            ],
        }
        _set_optional(payload, "support_score", self.support_score)
        _set_optional(payload, "counterevidence_score", self.counterevidence_score)
        _set_optional(payload, "total_score", self.total_score)
        _set_optional(payload, "order_hypothesis_key", self.order_hypothesis_key)
        _set_optional(payload, "spatial_candidate_key", self.spatial_candidate_key)
        _set_optional(payload, "location_proof_basis", self.location_proof_basis)
        _set_optional(payload, "supporting_window_count", self.supporting_window_count)
        _set_optional(payload, "supporting_duration_s", self.supporting_duration_s)
        _set_optional(payload, "supporting_sensor_count", self.supporting_sensor_count)
        _set_optional(payload, "stable_frequency_min_hz", self.stable_frequency_min_hz)
        _set_optional(payload, "stable_frequency_max_hz", self.stable_frequency_max_hz)
        _set_optional(payload, "dominant_location", self.dominant_location)
        _set_optional(payload, "runner_up_location", self.runner_up_location)
        _set_optional(payload, "dominant_phase", self.dominant_phase)
        _set_optional(payload, "dominant_speed_band", self.dominant_speed_band)
        _set_optional(payload, "location_separation_db", self.location_separation_db)
        _set_optional(payload, "dominance_ratio", self.dominance_ratio)
        _set_optional(payload, "alternative_source", self.alternative_source)
        _set_optional(payload, "confidence_gap_to_alternative", self.confidence_gap_to_alternative)
        _set_optional(payload, "fallback_reason", self.fallback_reason)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunDiagnosisSummary:
        raw_exemplars = data.get("exemplar_references")
        exemplars = (
            tuple(
                DiagnosisExemplarReference.from_mapping(row)
                for row in raw_exemplars
                if isinstance(row, dict)
            )
            if isinstance(raw_exemplars, list)
            else ()
        )
        raw_support_factors = data.get("support_factors")
        support_factors = (
            tuple(
                DiagnosisFactor.from_mapping(row)
                for row in raw_support_factors
                if isinstance(row, dict)
            )
            if isinstance(raw_support_factors, list)
            else ()
        )
        raw_counter_factors = data.get("counterevidence_factors")
        counter_factors = (
            tuple(
                DiagnosisFactor.from_mapping(row)
                for row in raw_counter_factors
                if isinstance(row, dict)
            )
            if isinstance(raw_counter_factors, list)
            else ()
        )
        return cls(
            diagnosis_key=_required_text(data, "diagnosis_key"),
            suspected_source=_required_text(data, "suspected_source"),
            rank=_required_int(data, "rank"),
            data_basis=_required_data_basis(data.get("data_basis")),
            support_score=_optional_float(data.get("support_score")),
            counterevidence_score=_optional_float(data.get("counterevidence_score")),
            total_score=_optional_float(data.get("total_score")),
            order_hypothesis_key=_optional_text(data.get("order_hypothesis_key")),
            spatial_candidate_key=_optional_text(data.get("spatial_candidate_key")),
            location_proof_basis=_optional_proof_basis(data.get("location_proof_basis")),
            supporting_window_count=_optional_int(data.get("supporting_window_count")),
            supporting_duration_s=_optional_float(data.get("supporting_duration_s")),
            supporting_sensor_count=_optional_int(data.get("supporting_sensor_count")),
            stable_frequency_min_hz=_optional_float(data.get("stable_frequency_min_hz")),
            stable_frequency_max_hz=_optional_float(data.get("stable_frequency_max_hz")),
            dominant_location=_optional_text(data.get("dominant_location")),
            runner_up_location=_optional_text(data.get("runner_up_location")),
            dominant_phase=_optional_text(data.get("dominant_phase")),
            dominant_speed_band=_optional_text(data.get("dominant_speed_band")),
            location_separation_db=_optional_float(data.get("location_separation_db")),
            dominance_ratio=_optional_float(data.get("dominance_ratio")),
            alternative_source=_optional_text(data.get("alternative_source")),
            confidence_gap_to_alternative=_optional_float(
                data.get("confidence_gap_to_alternative")
            ),
            ambiguous_diagnosis=_required_bool(data, "ambiguous_diagnosis"),
            ambiguous_location=_required_bool(data, "ambiguous_location"),
            suspicious=_required_bool(data, "suspicious"),
            weak_spatial_separation=_required_bool(data, "weak_spatial_separation"),
            has_reference_gap=_required_bool(data, "has_reference_gap"),
            uses_summary_fallback=_required_bool(data, "uses_summary_fallback"),
            fallback_reason=_optional_text(data.get("fallback_reason")),
            exemplar_references=exemplars,
            support_factors=support_factors,
            counterevidence_factors=counter_factors,
        )


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_nonnegative(value: int, *, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")


def _required_text(data: JsonObject, field_name: str) -> str:
    return _require_text(data.get(field_name), field_name=field_name)


def _required_int(data: JsonObject, field_name: str) -> int:
    return _required_int_field(
        data,
        field_name,
        invalid_message=f"{field_name} must be an int",
    )


def _required_bool(data: JsonObject, field_name: str) -> bool:
    return _required_bool_field(
        data,
        field_name,
        invalid_message=f"{field_name} must be a bool",
    )


def _required_numeric(data: JsonObject, field_name: str) -> float:
    return _required_float_field(
        data,
        field_name,
        invalid_message=f"{field_name} must be a number",
    )


def _required_exemplar_kind(value: object) -> DiagnosisExemplarKind:
    if value not in {
        "order_support_interval",
        "whole_run_context_interval",
        "spatial_location",
    }:
        raise ValueError("kind must be a supported diagnosis exemplar kind")
    return cast(DiagnosisExemplarKind, value)


def _require_factor_key(value: DiagnosisFactorKey) -> None:
    _required_factor_key(value)


def _required_factor_key(value: object) -> DiagnosisFactorKey:
    if value not in {
        "raw_backed",
        "partial_raw_backed",
        "repeated_support",
        "sustained_support",
        "stable_frequency",
        "tight_order_lock",
        "localized_support",
        "clean_signal",
        "user_confirmed_vehicle_data",
        "summary_only",
        "raw_replay_incomplete",
        "legacy_context",
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
        "secondary_vehicle_data",
        "approximate_vehicle_data",
        "unverified_vehicle_data",
    }:
        raise ValueError("factor_key must be a supported diagnosis factor key")
    return cast(DiagnosisFactorKey, value)


def _require_factor_polarity(value: DiagnosisFactorPolarity) -> None:
    _required_factor_polarity(value)


def _required_factor_polarity(value: object) -> DiagnosisFactorPolarity:
    if value not in {"support", "counterevidence"}:
        raise ValueError("polarity must be a supported diagnosis factor polarity")
    return cast(DiagnosisFactorPolarity, value)


def _require_factor_severity(value: DiagnosisFactorSeverity) -> None:
    _required_factor_severity(value)


def _required_factor_severity(value: object) -> DiagnosisFactorSeverity:
    if value not in {"low", "medium", "high"}:
        raise ValueError("severity must be a supported diagnosis factor severity")
    return cast(DiagnosisFactorSeverity, value)


def _required_data_basis(value: object) -> WholeRunDiagnosisDataBasis:
    if value not in {"raw_backed", "partial_raw_backed", "summary_only"}:
        raise ValueError("data_basis must be a supported whole-run diagnosis data basis")
    return cast(WholeRunDiagnosisDataBasis, value)


def _optional_proof_basis(value: object) -> LocationProofBasis | None:
    if value is None:
        return None
    if value not in {
        "whole_run_summary",
        "supporting_windows_raw_backed",
        "supporting_windows_summary_only",
    }:
        raise ValueError("location_proof_basis must be a supported location proof basis")
    return cast(LocationProofBasis, value)


def _optional_float(value: object) -> float | None:
    return _optional_float_or_none(value, strict=True)


def _optional_int(value: object) -> int | None:
    return _optional_int_or_none(value, strict=True)


def _optional_text(value: object) -> str | None:
    return _non_empty_text_or_none(value, strict=True)
