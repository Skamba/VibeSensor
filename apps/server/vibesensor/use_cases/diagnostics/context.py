"""Canonical typed diagnostics context used across the analysis core."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot, OrderReferenceSpec, Symptom
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import (
    PEAK_PICKER_METHOD,
    RUN_METADATA_TYPE,
    RUN_SCHEMA_VERSION,
)
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = ["DiagnosticsContext"]


@dataclass(frozen=True, slots=True)
class DiagnosticsContext:
    """Canonical diagnostics-only context above the persistence boundary."""

    record_type: str = RUN_METADATA_TYPE
    schema_version: str = RUN_SCHEMA_VERSION
    run_id: str = ""
    start_time_utc: str = ""
    end_time_utc: str | None = None
    sensor_model: str = "unknown"
    firmware_version: str | None = None
    raw_sample_rate_hz: int | None = None
    feature_interval_s: float | None = None
    fft_window_size_samples: int | None = None
    fft_window_type: str | None = None
    peak_picker_method: str = PEAK_PICKER_METHOD
    accel_scale_g_per_lsb: float | None = None
    incomplete_for_order_analysis: bool = False
    analysis_settings: AnalysisSettingsSnapshot = field(default_factory=AnalysisSettingsSnapshot)
    car: CarSnapshot | None = None
    case_id: str = ""
    sensor_mac: str | None = None
    summary_version: int = 1
    symptom: Symptom | None = None
    report_date: str | None = None
    language: str = "en"
    explicit_engine_rpm: float | None = None
    tire_circumference_m_override: float | None = None
    units: JsonObject | None = None
    amplitude_definitions: JsonObject | None = None
    recorded_utc_offset_seconds: int | None = None

    @property
    def active_car_id(self) -> str | None:
        return self.car.car_id if self.car is not None else None

    @property
    def car_name(self) -> str | None:
        return self.car.name if self.car is not None else None

    @property
    def car_type(self) -> str | None:
        return self.car.car_type if self.car is not None else None

    @property
    def car_variant(self) -> str | None:
        return self.car.variant if self.car is not None else None

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        return order_reference_spec_from_snapshot(self.analysis_settings)

    @property
    def tire_circumference_m(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.supports_wheel_reference:
            return spec.tire_circumference_m
        override = self.tire_circumference_m_override
        if override is not None and override > 0:
            return override
        return None

    def order_reference_spec_for(
        self,
        sample: SensorFrame | None = None,
    ) -> OrderReferenceSpec | None:
        spec = self.order_reference_spec
        if sample is None or spec is None:
            return spec
        final_drive = sample.final_drive_ratio
        gear_ratio = sample.gear
        if final_drive is None and gear_ratio is None:
            return spec
        return replace(
            spec,
            final_drive_ratio=final_drive if final_drive is not None else spec.final_drive_ratio,
            current_gear_ratio=gear_ratio if gear_ratio is not None else spec.current_gear_ratio,
        )

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
    def reference_complete(self) -> bool:
        spec = self.order_reference_spec
        return bool(
            self.raw_sample_rate_hz
            and self.tire_circumference_m
            and spec is not None
            and spec.is_complete
            and (self.explicit_engine_rpm is not None or spec.has_engine_reference)
        )
