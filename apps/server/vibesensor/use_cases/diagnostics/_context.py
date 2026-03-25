"""Typed diagnostics-internal run context.

Boundary metadata arrives as a raw JSON mapping from JSONL/history storage, but the
analysis pipeline should consume a typed object once that payload crosses the
boundary. ``DiagnosticsContext`` centralizes that normalization while preserving
round-trippable metadata for explicit serializer edges.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from vibesensor.domain import (
    OrderReferenceSpec,
    RunContextSnapshot,
    RunMetadataSnapshot,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float

from ._types import Sample

type ScalarSettingValue = int | float | bool | str
type ScalarSettings = tuple[tuple[str, ScalarSettingValue], ...]


@dataclass(frozen=True, slots=True)
class DiagnosticsContext:
    """Canonical typed diagnostics context built once at raw-metadata ingress."""

    run_metadata: RunMetadataSnapshot
    run_context: RunContextSnapshot
    start_time_utc: str | None = None
    end_time_utc: str | None = None
    report_date: str | None = None
    default_language: str = "en"
    fft_window_size_samples: int | None = None
    fft_window_type: str | None = None
    peak_picker_method: str | None = None
    accel_scale_g_per_lsb: float | None = None
    incomplete_for_order_analysis: bool = False
    symptom_description: str = ""
    symptom_onset: str = ""
    symptom_context: str = ""
    tire_circumference_m_override: float | None = None
    explicit_engine_rpm: float | None = None
    scalar_analysis_settings: ScalarSettings = ()
    _final_drive_ratio: float | None = None
    _current_gear_ratio: float | None = None
    _car_name: str | None = None
    _car_type: str | None = None
    _car_variant: str | None = None
    _fallback_order_reference_spec: OrderReferenceSpec | None = None
    _boundary_metadata: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self._boundary_metadata, MappingProxyType):
            object.__setattr__(
                self,
                "_boundary_metadata",
                MappingProxyType(dict(self._boundary_metadata)),
            )

    @property
    def run_id(self) -> str:
        return self.run_metadata.run_id

    @property
    def sensor_model(self) -> str | None:
        return self.run_metadata.sensor_model

    @property
    def firmware_version(self) -> str | None:
        return self.run_metadata.firmware_version

    @property
    def raw_sample_rate_hz(self) -> float | None:
        return self.run_metadata.raw_sample_rate_hz

    @property
    def feature_interval_s(self) -> float | None:
        return self.run_metadata.feature_interval_s

    @property
    def car_name(self) -> str | None:
        return self.run_context.car_name or self._car_name

    @property
    def car_type(self) -> str | None:
        return self.run_context.car_type or self._car_type

    @property
    def car_variant(self) -> str | None:
        return self.run_context.car_variant or self._car_variant

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        run_context_spec = self.run_context.order_reference_spec
        fallback_spec = self._fallback_order_reference_spec
        if _reference_spec_score(fallback_spec) > _reference_spec_score(run_context_spec):
            return fallback_spec
        return run_context_spec or fallback_spec

    @property
    def final_drive_ratio(self) -> float | None:
        if self._final_drive_ratio is not None:
            return self._final_drive_ratio
        spec = self.order_reference_spec
        return _as_float(getattr(spec, "final_drive_ratio", None)) if spec is not None else None

    @property
    def current_gear_ratio(self) -> float | None:
        if self._current_gear_ratio is not None:
            return self._current_gear_ratio
        spec = self.order_reference_spec
        return _as_float(getattr(spec, "current_gear_ratio", None)) if spec is not None else None

    @property
    def tire_circumference_m(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and bool(getattr(spec, "supports_wheel_reference", False)):
            return _as_float(getattr(spec, "tire_circumference_m", None))
        override = self.tire_circumference_m_override
        if override is not None and override > 0:
            return override
        return None

    @property
    def reference_complete(self) -> bool:
        spec = self.order_reference_spec
        return bool(
            self.raw_sample_rate_hz
            and self.tire_circumference_m
            and spec is not None
            and bool(getattr(spec, "is_complete", False))
            and (
                self.explicit_engine_rpm is not None
                or bool(getattr(spec, "has_engine_reference", False))
            )
        )

    def effective_order_reference_spec(
        self,
        sample: Sample | None = None,
    ) -> OrderReferenceSpec | None:
        """Return the base order-reference spec, optionally overridden by one sample."""
        spec = self.order_reference_spec
        if sample is None or spec is None:
            return spec
        final_drive_ratio = sample.final_drive_ratio
        gear_ratio = sample.gear
        if final_drive_ratio is None and gear_ratio is None:
            return spec
        return replace(
            spec,
            final_drive_ratio=(
                final_drive_ratio if final_drive_ratio is not None else spec.final_drive_ratio
            ),
            current_gear_ratio=(gear_ratio if gear_ratio is not None else spec.current_gear_ratio),
        )


def _reference_spec_score(spec: OrderReferenceSpec | None) -> int:
    if spec is None:
        return 0
    return (
        int(bool(getattr(spec, "supports_wheel_reference", False)))
        + int(bool(getattr(spec, "supports_driveshaft_reference", False)))
        + int(
            bool(getattr(spec, "supports_engine_reference", False)),
        )
    )


__all__ = ["DiagnosticsContext"]
