"""Whole-run multi-sensor spatial/coherence contracts.

Dense window rows stay keyed by ``(candidate_key, window_index, sensor_id)`` so
later execution stages can join aligned per-window sensor outputs without
inventing a second spatial evidence vocabulary. Compact summaries carry only the
report/history-facing proof fields needed after persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from vibesensor.shared.types.history_analysis_contracts import LocationProofBasis
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.whole_run_json_helpers import (
    non_empty_text_or_none as _non_empty_text_or_none,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    optional_float_or_none as _optional_float_or_none,
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
    "LocationProofBasis",
    "SpatialEvidenceSummary",
    "SpatialEvidenceWindow",
    "SpatialLocationSummary",
]


@dataclass(frozen=True, slots=True)
class SpatialEvidenceWindow:
    """Dense spatial/coherence evidence row for one candidate-window-sensor join."""

    candidate_key: str
    suspected_source: str
    window_index: int
    sensor_id: str
    location: str
    supporting: bool
    coherent: bool
    peak_intensity_db: float | None = None
    vibration_strength_db: float | None = None
    matched_frequency_hz: float | None = None
    coherence_score: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.candidate_key, field_name="candidate_key")
        _require_text(self.suspected_source, field_name="suspected_source")
        _require_text(self.sensor_id, field_name="sensor_id")
        _require_text(self.location, field_name="location")
        _require_nonnegative(self.window_index, field_name="window_index")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "candidate_key": self.candidate_key,
            "suspected_source": self.suspected_source,
            "window_index": self.window_index,
            "sensor_id": self.sensor_id,
            "location": self.location,
            "supporting": self.supporting,
            "coherent": self.coherent,
        }
        _set_optional(payload, "peak_intensity_db", self.peak_intensity_db)
        _set_optional(payload, "vibration_strength_db", self.vibration_strength_db)
        _set_optional(payload, "matched_frequency_hz", self.matched_frequency_hz)
        _set_optional(payload, "coherence_score", self.coherence_score)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> SpatialEvidenceWindow:
        return cls(
            candidate_key=_required_text(data, "candidate_key"),
            suspected_source=_required_text(data, "suspected_source"),
            window_index=_required_int(data, "window_index"),
            sensor_id=_required_text(data, "sensor_id"),
            location=_required_text(data, "location"),
            supporting=_required_bool(data, "supporting"),
            coherent=_required_bool(data, "coherent"),
            peak_intensity_db=_optional_float(data.get("peak_intensity_db")),
            vibration_strength_db=_optional_float(data.get("vibration_strength_db")),
            matched_frequency_hz=_optional_float(data.get("matched_frequency_hz")),
            coherence_score=_optional_float(data.get("coherence_score")),
        )


@dataclass(frozen=True, slots=True)
class SpatialLocationSummary:
    """Compact per-location support row for persisted spatial evidence."""

    location: str
    sensor_ids: tuple[str, ...]
    supporting_window_count: int
    support_ratio: float
    coherent_window_count: int = 0
    coherence_ratio: float | None = None
    peak_intensity_db: float | None = None
    mean_vibration_strength_db: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.location, field_name="location")
        _require_nonnegative(self.supporting_window_count, field_name="supporting_window_count")
        _require_nonnegative(self.coherent_window_count, field_name="coherent_window_count")
        _require_ratio(self.support_ratio, field_name="support_ratio")
        if self.coherence_ratio is not None:
            _require_ratio(self.coherence_ratio, field_name="coherence_ratio")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "location": self.location,
            "sensor_ids": list(self.sensor_ids),
            "supporting_window_count": self.supporting_window_count,
            "support_ratio": self.support_ratio,
            "coherent_window_count": self.coherent_window_count,
        }
        _set_optional(payload, "coherence_ratio", self.coherence_ratio)
        _set_optional(payload, "peak_intensity_db", self.peak_intensity_db)
        _set_optional(
            payload,
            "mean_vibration_strength_db",
            self.mean_vibration_strength_db,
        )
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> SpatialLocationSummary:
        return cls(
            location=_required_text(data, "location"),
            sensor_ids=_text_tuple(data.get("sensor_ids")),
            supporting_window_count=_required_int(data, "supporting_window_count"),
            support_ratio=_required_float(data, "support_ratio"),
            coherent_window_count=_required_int(data, "coherent_window_count"),
            coherence_ratio=_optional_float(data.get("coherence_ratio")),
            peak_intensity_db=_optional_float(data.get("peak_intensity_db")),
            mean_vibration_strength_db=_optional_float(data.get("mean_vibration_strength_db")),
        )


@dataclass(frozen=True, slots=True)
class SpatialEvidenceSummary:
    """Compact persisted/report-facing whole-run spatial evidence summary."""

    candidate_key: str
    suspected_source: str
    proof_basis: LocationProofBasis
    total_window_count: int
    supporting_window_count: int
    supporting_sensor_count: int
    coherent_window_count: int = 0
    coherence_ratio: float | None = None
    dominant_location: str | None = None
    runner_up_location: str | None = None
    location_separation_db: float | None = None
    dominance_ratio: float | None = None
    ambiguous_location: bool = False
    weak_spatial_separation: bool = False
    location_summaries: tuple[SpatialLocationSummary, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.candidate_key, field_name="candidate_key")
        _require_text(self.suspected_source, field_name="suspected_source")
        _require_nonnegative(self.total_window_count, field_name="total_window_count")
        _require_nonnegative(
            self.supporting_window_count,
            field_name="supporting_window_count",
        )
        _require_nonnegative(
            self.supporting_sensor_count,
            field_name="supporting_sensor_count",
        )
        _require_nonnegative(self.coherent_window_count, field_name="coherent_window_count")
        if self.coherence_ratio is not None:
            _require_ratio(self.coherence_ratio, field_name="coherence_ratio")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "candidate_key": self.candidate_key,
            "suspected_source": self.suspected_source,
            "proof_basis": self.proof_basis,
            "total_window_count": self.total_window_count,
            "supporting_window_count": self.supporting_window_count,
            "supporting_sensor_count": self.supporting_sensor_count,
            "coherent_window_count": self.coherent_window_count,
            "ambiguous_location": self.ambiguous_location,
            "weak_spatial_separation": self.weak_spatial_separation,
            "location_summaries": [summary.to_json_object() for summary in self.location_summaries],
        }
        _set_optional(payload, "coherence_ratio", self.coherence_ratio)
        _set_optional(payload, "dominant_location", self.dominant_location)
        _set_optional(payload, "runner_up_location", self.runner_up_location)
        _set_optional(payload, "location_separation_db", self.location_separation_db)
        _set_optional(payload, "dominance_ratio", self.dominance_ratio)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> SpatialEvidenceSummary:
        raw_location_summaries = data.get("location_summaries")
        location_summaries = (
            tuple(
                SpatialLocationSummary.from_mapping(row)
                for row in raw_location_summaries
                if isinstance(row, dict)
            )
            if isinstance(raw_location_summaries, list)
            else ()
        )
        return cls(
            candidate_key=_required_text(data, "candidate_key"),
            suspected_source=_required_text(data, "suspected_source"),
            proof_basis=_required_proof_basis(data.get("proof_basis")),
            total_window_count=_required_int(data, "total_window_count"),
            supporting_window_count=_required_int(data, "supporting_window_count"),
            supporting_sensor_count=_required_int(data, "supporting_sensor_count"),
            coherent_window_count=_required_int(data, "coherent_window_count"),
            coherence_ratio=_optional_float(data.get("coherence_ratio")),
            dominant_location=_optional_text(data.get("dominant_location")),
            runner_up_location=_optional_text(data.get("runner_up_location")),
            location_separation_db=_optional_float(data.get("location_separation_db")),
            dominance_ratio=_optional_float(data.get("dominance_ratio")),
            ambiguous_location=_required_bool(data, "ambiguous_location"),
            weak_spatial_separation=_required_bool(data, "weak_spatial_separation"),
            location_summaries=location_summaries,
        )


def _require_text(value: object, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_nonnegative(value: int, *, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")


def _require_ratio(value: float, *, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")


def _required_text(data: JsonObject, field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _required_int(data: JsonObject, field_name: str) -> int:
    return _required_int_field(
        data,
        field_name,
        invalid_message=f"{field_name} must be an int",
    )


def _required_float(data: JsonObject, field_name: str) -> float:
    return _required_float_field(
        data,
        field_name,
        invalid_message=f"{field_name} must be a number",
    )


def _required_bool(data: JsonObject, field_name: str) -> bool:
    return _required_bool_field(
        data,
        field_name,
        invalid_message=f"{field_name} must be a bool",
    )


def _required_proof_basis(value: object) -> LocationProofBasis:
    if value not in {
        "whole_run_summary",
        "supporting_windows_raw_backed",
        "supporting_windows_summary_only",
    }:
        raise ValueError("proof_basis must be a supported location proof basis")
    return cast(LocationProofBasis, value)


def _optional_float(value: object) -> float | None:
    return _optional_float_or_none(value, strict=True)


def _optional_text(value: object) -> str | None:
    return _non_empty_text_or_none(value, strict=True)


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
