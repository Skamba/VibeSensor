"""Canonical typed diagnostics run context."""

from __future__ import annotations

from dataclasses import dataclass, replace

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot, OrderReferenceSpec, Symptom
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    ScalarSettings,
    analysis_settings_snapshot_items,
)
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame


@dataclass(frozen=True, slots=True)
class DiagnosticsContext:
    """Thin typed diagnostics view over canonical run metadata."""

    metadata: RunMetadata

    def __post_init__(self) -> None:
        if not self.metadata.run_id:
            raise ValueError("run_id must be a non-empty string")
        if self.metadata.summary_version < 1:
            raise ValueError("summary_version must be >= 1")

    @property
    def run_id(self) -> str:
        return self.metadata.run_id

    @property
    def case_id(self) -> str:
        return self.metadata.case_id

    @property
    def sensor_mac(self) -> str | None:
        return self.metadata.sensor_mac

    @property
    def sensor_model(self) -> str:
        return self.metadata.sensor_model

    @property
    def firmware_version(self) -> str | None:
        return self.metadata.firmware_version

    @property
    def raw_sample_rate_hz(self) -> float | None:
        value = self.metadata.raw_sample_rate_hz
        return float(value) if value is not None else None

    @property
    def feature_interval_s(self) -> float | None:
        return self.metadata.feature_interval_s

    @property
    def summary_version(self) -> int:
        return self.metadata.summary_version

    @property
    def analysis_settings(self) -> AnalysisSettingsSnapshot:
        return self.metadata.analysis_settings

    @property
    def car(self) -> CarSnapshot | None:
        return self.metadata.car

    @property
    def symptom(self) -> Symptom | None:
        return self.metadata.symptom

    @property
    def start_time_utc(self) -> str:
        return self.metadata.start_time_utc

    @property
    def end_time_utc(self) -> str | None:
        return self.metadata.end_time_utc

    @property
    def report_date(self) -> str | None:
        return self.metadata.report_date

    @property
    def default_language(self) -> str:
        return self.metadata.language

    @property
    def fft_window_size_samples(self) -> int | None:
        return self.metadata.fft_window_size_samples

    @property
    def fft_window_type(self) -> str | None:
        return self.metadata.fft_window_type

    @property
    def peak_picker_method(self) -> str:
        return self.metadata.peak_picker_method

    @property
    def accel_scale_g_per_lsb(self) -> float | None:
        return self.metadata.accel_scale_g_per_lsb

    @property
    def incomplete_for_order_analysis(self) -> bool:
        return self.metadata.incomplete_for_order_analysis

    @property
    def tire_circumference_m_override(self) -> float | None:
        return self.metadata.tire_circumference_m_override

    @property
    def explicit_engine_rpm(self) -> float | None:
        return self.metadata.explicit_engine_rpm

    @property
    def units(self) -> JsonObject | None:
        return self.metadata.units

    @property
    def amplitude_definitions(self) -> JsonObject | None:
        return self.metadata.amplitude_definitions

    @property
    def car_name(self) -> str | None:
        return self.metadata.car_name

    @property
    def car_type(self) -> str | None:
        return self.metadata.car_type

    @property
    def car_variant(self) -> str | None:
        return self.metadata.car_variant

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        return self.metadata.order_reference_spec

    @property
    def final_drive_ratio(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.final_drive_ratio > 0:
            return spec.final_drive_ratio
        ratio = self.analysis_settings.final_drive_ratio
        return ratio if ratio > 0 else None

    @property
    def current_gear_ratio(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.current_gear_ratio > 0:
            return spec.current_gear_ratio
        ratio = self.analysis_settings.current_gear_ratio
        return ratio if ratio > 0 else None

    @property
    def tire_circumference_m(self) -> float | None:
        return self.metadata.tire_circumference_m

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

    @property
    def analysis_settings_items(self) -> ScalarSettings:
        return analysis_settings_snapshot_items(self.analysis_settings)

    def effective_order_reference_spec(
        self,
        sample: SensorFrame | None = None,
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


__all__ = ["DiagnosticsContext"]
