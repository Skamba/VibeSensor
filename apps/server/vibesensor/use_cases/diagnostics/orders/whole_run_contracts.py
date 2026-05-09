"""Whole-run order-trace contracts for dense sidecars and compact summaries.

The dense trace stays keyed by ``(hypothesis_key, harmonic, window_index)`` so
later execution stages can join directly against the canonical whole-run window
grid without inventing a second order model. Compact summaries collapse those
dense points into persisted/report-facing support intervals, phase support, and
harmonic evidence rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    required_non_empty_text as _required_non_empty_text,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    set_optional_value as _set_optional,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    tuple_from_mapping_list_field as _tuple_from_mapping_list_field,
)

__all__ = [
    "OrderHarmonicEvidenceSummary",
    "ORDER_TRACE_FAMILY_VALUES",
    "OrderTraceFamily",
    "OrderTracePhaseSupport",
    "OrderTracePoint",
    "OrderTraceSummary",
    "OrderTraceSupportInterval",
]

type OrderTraceFamily = Literal["wheel", "driveshaft", "engine"]

ORDER_TRACE_FAMILY_VALUES: frozenset[OrderTraceFamily] = frozenset(
    {"wheel", "driveshaft", "engine"}
)


@dataclass(frozen=True, slots=True)
class OrderTracePoint:
    """Dense whole-run order-trace point keyed to one candidate, harmonic, and window."""

    hypothesis_key: str
    suspected_source: str
    order_family: OrderTraceFamily
    harmonic: int
    order_label: str
    window_index: int
    eligible: bool
    matched: bool
    predicted_hz: float | None = None
    matched_hz: float | None = None
    relative_error: float | None = None
    peak_intensity_db: float | None = None
    vibration_strength_db: float | None = None
    ref_source: str | None = None
    strongest_location: str | None = None
    window_quality_score: float | None = None
    window_quality_state: str | None = None
    window_quality_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonnegative(self.window_index, field_name="window_index")
        _require_positive(self.harmonic, field_name="harmonic")
        _require_text(self.hypothesis_key, field_name="hypothesis_key")
        _require_text(self.order_label, field_name="order_label")
        _require_text(self.suspected_source, field_name="suspected_source")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "hypothesis_key": self.hypothesis_key,
            "suspected_source": self.suspected_source,
            "order_family": self.order_family,
            "harmonic": self.harmonic,
            "order_label": self.order_label,
            "window_index": self.window_index,
            "eligible": self.eligible,
            "matched": self.matched,
        }
        _set_optional(payload, "predicted_hz", self.predicted_hz)
        _set_optional(payload, "matched_hz", self.matched_hz)
        _set_optional(payload, "relative_error", self.relative_error)
        _set_optional(payload, "peak_intensity_db", self.peak_intensity_db)
        _set_optional(payload, "vibration_strength_db", self.vibration_strength_db)
        _set_optional(payload, "ref_source", self.ref_source)
        _set_optional(payload, "strongest_location", self.strongest_location)
        _set_optional(payload, "window_quality_score", self.window_quality_score)
        _set_optional(payload, "window_quality_state", self.window_quality_state)
        if self.window_quality_reasons:
            payload["window_quality_reasons"] = list(self.window_quality_reasons)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> OrderTracePoint:
        return cls(
            hypothesis_key=_required_text(data, "hypothesis_key"),
            suspected_source=_required_text(data, "suspected_source"),
            order_family=_order_family(data.get("order_family")),
            harmonic=_required_int(data, "harmonic"),
            order_label=_required_text(data, "order_label"),
            window_index=_required_int(data, "window_index"),
            eligible=_required_bool(data, "eligible"),
            matched=_required_bool(data, "matched"),
            predicted_hz=_optional_float(data.get("predicted_hz")),
            matched_hz=_optional_float(data.get("matched_hz")),
            relative_error=_optional_float(data.get("relative_error")),
            peak_intensity_db=_optional_float(data.get("peak_intensity_db")),
            vibration_strength_db=_optional_float(data.get("vibration_strength_db")),
            ref_source=_optional_text(data.get("ref_source")),
            strongest_location=_optional_text(data.get("strongest_location")),
            window_quality_score=_optional_float(data.get("window_quality_score")),
            window_quality_state=_optional_text(data.get("window_quality_state")),
            window_quality_reasons=_text_tuple(data.get("window_quality_reasons")),
        )


@dataclass(frozen=True, slots=True)
class OrderTraceSupportInterval:
    """Compact contiguous support interval derived from dense whole-run trace points."""

    interval_index: int
    start_window_index: int
    end_window_index: int
    matched_window_count: int
    support_ratio: float
    start_t_s: float | None = None
    end_t_s: float | None = None
    phase: str | None = None
    load_state: str | None = None
    speed_band: str | None = None
    mean_relative_error: float | None = None

    def __post_init__(self) -> None:
        _require_nonnegative(self.interval_index, field_name="interval_index")
        _require_nonnegative(self.start_window_index, field_name="start_window_index")
        _require_nonnegative(self.end_window_index, field_name="end_window_index")
        if self.end_window_index < self.start_window_index:
            raise ValueError("end_window_index must be >= start_window_index")
        _require_nonnegative(self.matched_window_count, field_name="matched_window_count")
        _require_ratio(self.support_ratio, field_name="support_ratio")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "interval_index": self.interval_index,
            "start_window_index": self.start_window_index,
            "end_window_index": self.end_window_index,
            "matched_window_count": self.matched_window_count,
            "support_ratio": self.support_ratio,
        }
        _set_optional(payload, "start_t_s", self.start_t_s)
        _set_optional(payload, "end_t_s", self.end_t_s)
        _set_optional(payload, "phase", self.phase)
        _set_optional(payload, "load_state", self.load_state)
        _set_optional(payload, "speed_band", self.speed_band)
        _set_optional(payload, "mean_relative_error", self.mean_relative_error)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> OrderTraceSupportInterval:
        return cls(
            interval_index=_required_int(data, "interval_index"),
            start_window_index=_required_int(data, "start_window_index"),
            end_window_index=_required_int(data, "end_window_index"),
            matched_window_count=_required_int(data, "matched_window_count"),
            support_ratio=_required_float(data, "support_ratio"),
            start_t_s=_optional_float(data.get("start_t_s")),
            end_t_s=_optional_float(data.get("end_t_s")),
            phase=_optional_text(data.get("phase")),
            load_state=_optional_text(data.get("load_state")),
            speed_band=_optional_text(data.get("speed_band")),
            mean_relative_error=_optional_float(data.get("mean_relative_error")),
        )


@dataclass(frozen=True, slots=True)
class OrderTracePhaseSupport:
    """Compact phase-aware support row for one order-trace summary."""

    phase: str
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float

    def __post_init__(self) -> None:
        _require_text(self.phase, field_name="phase")
        _require_nonnegative(self.eligible_window_count, field_name="eligible_window_count")
        _require_nonnegative(self.matched_window_count, field_name="matched_window_count")
        _require_ratio(self.support_ratio, field_name="support_ratio")

    def to_json_object(self) -> JsonObject:
        return {
            "phase": self.phase,
            "eligible_window_count": self.eligible_window_count,
            "matched_window_count": self.matched_window_count,
            "support_ratio": self.support_ratio,
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> OrderTracePhaseSupport:
        return cls(
            phase=_required_text(data, "phase"),
            eligible_window_count=_required_int(data, "eligible_window_count"),
            matched_window_count=_required_int(data, "matched_window_count"),
            support_ratio=_required_float(data, "support_ratio"),
        )


@dataclass(frozen=True, slots=True)
class OrderHarmonicEvidenceSummary:
    """Compact harmonic-specific evidence row for one order-trace summary."""

    harmonic: int
    order_label: str
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float
    reference_coverage_ratio: float
    contiguous_support_ratio: float
    lock_score: float
    mean_relative_error: float | None = None
    relative_error_stddev: float | None = None
    drift_score: float = 0.0
    peak_intensity_db: float | None = None
    mean_vibration_strength_db: float | None = None

    def __post_init__(self) -> None:
        _require_positive(self.harmonic, field_name="harmonic")
        _require_text(self.order_label, field_name="order_label")
        _require_nonnegative(self.eligible_window_count, field_name="eligible_window_count")
        _require_nonnegative(self.matched_window_count, field_name="matched_window_count")
        _require_ratio(self.support_ratio, field_name="support_ratio")
        _require_ratio(self.reference_coverage_ratio, field_name="reference_coverage_ratio")
        _require_ratio(self.contiguous_support_ratio, field_name="contiguous_support_ratio")
        _require_ratio(self.lock_score, field_name="lock_score")
        _require_ratio(self.drift_score, field_name="drift_score")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "harmonic": self.harmonic,
            "order_label": self.order_label,
            "eligible_window_count": self.eligible_window_count,
            "matched_window_count": self.matched_window_count,
            "support_ratio": self.support_ratio,
            "reference_coverage_ratio": self.reference_coverage_ratio,
            "contiguous_support_ratio": self.contiguous_support_ratio,
            "lock_score": self.lock_score,
            "drift_score": self.drift_score,
        }
        _set_optional(payload, "mean_relative_error", self.mean_relative_error)
        _set_optional(payload, "relative_error_stddev", self.relative_error_stddev)
        _set_optional(payload, "peak_intensity_db", self.peak_intensity_db)
        _set_optional(payload, "mean_vibration_strength_db", self.mean_vibration_strength_db)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> OrderHarmonicEvidenceSummary:
        return cls(
            harmonic=_required_int(data, "harmonic"),
            order_label=_required_text(data, "order_label"),
            eligible_window_count=_required_int(data, "eligible_window_count"),
            matched_window_count=_required_int(data, "matched_window_count"),
            support_ratio=_required_float(data, "support_ratio"),
            reference_coverage_ratio=_required_float(data, "reference_coverage_ratio"),
            contiguous_support_ratio=_required_float(data, "contiguous_support_ratio"),
            lock_score=_required_float(data, "lock_score"),
            mean_relative_error=_optional_float(data.get("mean_relative_error")),
            relative_error_stddev=_optional_float(data.get("relative_error_stddev")),
            drift_score=_required_float(data, "drift_score"),
            peak_intensity_db=_optional_float(data.get("peak_intensity_db")),
            mean_vibration_strength_db=_optional_float(data.get("mean_vibration_strength_db")),
        )


@dataclass(frozen=True, slots=True)
class OrderTraceSummary:
    """Compact persisted/report-facing summary derived from dense whole-run order traces."""

    hypothesis_key: str
    suspected_source: str
    order_family: OrderTraceFamily
    order_label: str
    total_window_count: int
    eligible_window_count: int
    matched_window_count: int
    support_ratio: float
    reference_coverage_ratio: float
    longest_contiguous_support_window_count: int
    contiguous_support_ratio: float
    usable_window_count: int = 0
    limited_window_count: int = 0
    excluded_window_count: int = 0
    mean_quality_score: float | None = None
    support_intervals: tuple[OrderTraceSupportInterval, ...] = ()
    phase_support: tuple[OrderTracePhaseSupport, ...] = ()
    harmonic_summaries: tuple[OrderHarmonicEvidenceSummary, ...] = ()
    stable_frequency_min_hz: float | None = None
    stable_frequency_max_hz: float | None = None
    exemplar_interval_index: int | None = None
    dominant_phase: str | None = None
    dominant_speed_band: str | None = None
    strongest_location: str | None = None
    mean_relative_error: float | None = None
    relative_error_stddev: float | None = None
    drift_score: float = 0.0
    lock_score: float = 0.0
    peak_intensity_db: float | None = None
    mean_vibration_strength_db: float | None = None
    ref_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.hypothesis_key, field_name="hypothesis_key")
        _require_text(self.suspected_source, field_name="suspected_source")
        _require_text(self.order_label, field_name="order_label")
        _require_nonnegative(self.total_window_count, field_name="total_window_count")
        _require_nonnegative(self.eligible_window_count, field_name="eligible_window_count")
        _require_nonnegative(self.matched_window_count, field_name="matched_window_count")
        _require_nonnegative(
            self.longest_contiguous_support_window_count,
            field_name="longest_contiguous_support_window_count",
        )
        _require_nonnegative(self.usable_window_count, field_name="usable_window_count")
        _require_nonnegative(self.limited_window_count, field_name="limited_window_count")
        _require_nonnegative(self.excluded_window_count, field_name="excluded_window_count")
        _require_ratio(self.support_ratio, field_name="support_ratio")
        _require_ratio(self.reference_coverage_ratio, field_name="reference_coverage_ratio")
        _require_ratio(self.contiguous_support_ratio, field_name="contiguous_support_ratio")
        _require_ratio(self.drift_score, field_name="drift_score")
        _require_ratio(self.lock_score, field_name="lock_score")
        if self.exemplar_interval_index is not None:
            _require_nonnegative(self.exemplar_interval_index, field_name="exemplar_interval_index")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "hypothesis_key": self.hypothesis_key,
            "suspected_source": self.suspected_source,
            "order_family": self.order_family,
            "order_label": self.order_label,
            "total_window_count": self.total_window_count,
            "eligible_window_count": self.eligible_window_count,
            "matched_window_count": self.matched_window_count,
            "support_ratio": self.support_ratio,
            "reference_coverage_ratio": self.reference_coverage_ratio,
            "longest_contiguous_support_window_count": self.longest_contiguous_support_window_count,
            "contiguous_support_ratio": self.contiguous_support_ratio,
            "usable_window_count": self.usable_window_count,
            "limited_window_count": self.limited_window_count,
            "excluded_window_count": self.excluded_window_count,
            "support_intervals": [interval.to_json_object() for interval in self.support_intervals],
            "phase_support": [row.to_json_object() for row in self.phase_support],
            "harmonic_summaries": [summary.to_json_object() for summary in self.harmonic_summaries],
            "drift_score": self.drift_score,
            "lock_score": self.lock_score,
            "ref_sources": list(self.ref_sources),
        }
        _set_optional(payload, "stable_frequency_min_hz", self.stable_frequency_min_hz)
        _set_optional(payload, "stable_frequency_max_hz", self.stable_frequency_max_hz)
        if self.exemplar_interval_index is not None:
            payload["exemplar_interval_index"] = self.exemplar_interval_index
        _set_optional(payload, "dominant_phase", self.dominant_phase)
        _set_optional(payload, "dominant_speed_band", self.dominant_speed_band)
        _set_optional(payload, "strongest_location", self.strongest_location)
        _set_optional(payload, "mean_relative_error", self.mean_relative_error)
        _set_optional(payload, "relative_error_stddev", self.relative_error_stddev)
        _set_optional(payload, "mean_quality_score", self.mean_quality_score)
        _set_optional(payload, "peak_intensity_db", self.peak_intensity_db)
        _set_optional(payload, "mean_vibration_strength_db", self.mean_vibration_strength_db)
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> OrderTraceSummary:
        return cls(
            hypothesis_key=_required_text(data, "hypothesis_key"),
            suspected_source=_required_text(data, "suspected_source"),
            order_family=_order_family(data.get("order_family")),
            order_label=_required_text(data, "order_label"),
            total_window_count=_required_int(data, "total_window_count"),
            eligible_window_count=_required_int(data, "eligible_window_count"),
            matched_window_count=_required_int(data, "matched_window_count"),
            support_ratio=_required_float(data, "support_ratio"),
            reference_coverage_ratio=_required_float(data, "reference_coverage_ratio"),
            longest_contiguous_support_window_count=_required_int(
                data,
                "longest_contiguous_support_window_count",
            ),
            contiguous_support_ratio=_required_float(data, "contiguous_support_ratio"),
            usable_window_count=_optional_int(data.get("usable_window_count")) or 0,
            limited_window_count=_optional_int(data.get("limited_window_count")) or 0,
            excluded_window_count=_optional_int(data.get("excluded_window_count")) or 0,
            mean_quality_score=_optional_float(data.get("mean_quality_score")),
            support_intervals=_tuple_from_mapping_list_field(
                data,
                "support_intervals",
                OrderTraceSupportInterval.from_mapping,
            ),
            phase_support=_tuple_from_mapping_list_field(
                data,
                "phase_support",
                OrderTracePhaseSupport.from_mapping,
            ),
            harmonic_summaries=_tuple_from_mapping_list_field(
                data,
                "harmonic_summaries",
                OrderHarmonicEvidenceSummary.from_mapping,
            ),
            stable_frequency_min_hz=_optional_float(data.get("stable_frequency_min_hz")),
            stable_frequency_max_hz=_optional_float(data.get("stable_frequency_max_hz")),
            exemplar_interval_index=_optional_int(data.get("exemplar_interval_index")),
            dominant_phase=_optional_text(data.get("dominant_phase")),
            dominant_speed_band=_optional_text(data.get("dominant_speed_band")),
            strongest_location=_optional_text(data.get("strongest_location")),
            mean_relative_error=_optional_float(data.get("mean_relative_error")),
            relative_error_stddev=_optional_float(data.get("relative_error_stddev")),
            drift_score=_required_float(data, "drift_score"),
            lock_score=_required_float(data, "lock_score"),
            peak_intensity_db=_optional_float(data.get("peak_intensity_db")),
            mean_vibration_strength_db=_optional_float(data.get("mean_vibration_strength_db")),
            ref_sources=_text_tuple(data.get("ref_sources")),
        )


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for raw in value if (text := _optional_text(raw)) is not None)


def _required_text(data: JsonObject, field: str) -> str:
    return _required_non_empty_text(
        data,
        field,
        invalid_message=f"{field} requires a non-empty string",
    )


def _optional_text(value: object) -> str | None:
    return _non_empty_text_or_none(value)


def _required_bool(data: JsonObject, field: str) -> bool:
    return _required_bool_field(
        data,
        field,
        invalid_message=f"{field} requires a boolean value",
    )


def _required_int(data: JsonObject, field: str) -> int:
    return _required_int_field(
        data,
        field,
        invalid_message=f"{field} requires an integer value",
    )


def _required_float(data: JsonObject, field: str) -> float:
    return _required_float_field(
        data,
        field,
        invalid_message=f"{field} requires a numeric value",
    )


def _optional_int(value: object) -> int | None:
    return _optional_int_or_none(value)


def _optional_float(value: object) -> float | None:
    return _optional_float_or_none(value)


def _order_family(value: object) -> OrderTraceFamily:
    family = _optional_text(value)
    if family == "wheel":
        return "wheel"
    if family == "driveshaft":
        return "driveshaft"
    if family == "engine":
        return "engine"
    raise ValueError(f"Unsupported order_family {value!r}")


def _require_nonnegative(value: int, *, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")


def _require_positive(value: int, *, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0")


def _require_text(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_ratio(value: float, *, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be in [0, 1]")
