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
    present_boundary_keys: frozenset[str] = frozenset()
    passthrough_metadata: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.passthrough_metadata, MappingProxyType):
            object.__setattr__(
                self,
                "passthrough_metadata",
                MappingProxyType(dict(self.passthrough_metadata)),
            )
        if not isinstance(self.present_boundary_keys, frozenset):
            object.__setattr__(self, "present_boundary_keys", frozenset(self.present_boundary_keys))

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
        return self.run_context.car_name

    @property
    def car_type(self) -> str | None:
        return self.run_context.car_type

    @property
    def car_variant(self) -> str | None:
        return self.run_context.car_variant

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        return self.run_context.order_reference_spec

    @property
    def final_drive_ratio(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.final_drive_ratio > 0:
            return spec.final_drive_ratio
        ratio = self.run_context.analysis_settings.final_drive_ratio
        return ratio if ratio > 0 else None

    @property
    def current_gear_ratio(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.current_gear_ratio > 0:
            return spec.current_gear_ratio
        ratio = self.run_context.analysis_settings.current_gear_ratio
        return ratio if ratio > 0 else None

    @property
    def tire_circumference_m(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and bool(getattr(spec, "supports_wheel_reference", False)):
            return spec.tire_circumference_m
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

    def has_boundary_key(self, key: str) -> bool:
        return key in self.present_boundary_keys


__all__ = ["DiagnosticsContext"]
