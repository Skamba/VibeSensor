"""Shared JSONL run-schema constants and canonical typed metadata contract."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    OrderReferenceSpec,
    Symptom,
)
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot

from .json_types import JsonObject

__all__ = [
    "FFT_WINDOW_TYPE",
    "PEAK_PICKER_METHOD",
    "RUN_END_TYPE",
    "RUN_METADATA_TYPE",
    "RUN_SAMPLE_TYPE",
    "RUN_SCHEMA_VERSION",
    "RunMetadata",
]

RUN_SCHEMA_VERSION = "v2-jsonl"
RUN_METADATA_TYPE = "run_metadata"
RUN_SAMPLE_TYPE = "sample"
RUN_END_TYPE = "run_end"
FFT_WINDOW_TYPE = "hann"
PEAK_PICKER_METHOD = "canonical_strength_metrics_module"


@dataclass(slots=True)
class RunMetadata:
    """Typed persisted run metadata with explicit run-context ownership."""

    record_type: str
    schema_version: str
    run_id: str
    start_time_utc: str
    end_time_utc: str | None
    sensor_model: str
    firmware_version: str | None
    raw_sample_rate_hz: int | None
    feature_interval_s: float | None
    fft_window_size_samples: int | None
    fft_window_type: str | None
    peak_picker_method: str
    accel_scale_g_per_lsb: float | None
    incomplete_for_order_analysis: bool
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

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        start_time_utc: str,
        sensor_model: str,
        raw_sample_rate_hz: int | None,
        feature_interval_s: float | None,
        fft_window_size_samples: int | None,
        accel_scale_g_per_lsb: float | None,
        firmware_version: str | None = None,
        end_time_utc: str | None = None,
        incomplete_for_order_analysis: bool = False,
        analysis_settings: AnalysisSettingsSnapshot | None = None,
        car: CarSnapshot | None = None,
        case_id: str = "",
        sensor_mac: str | None = None,
        summary_version: int = 1,
        symptom: Symptom | None = None,
        report_date: str | None = None,
        language: str = "en",
        explicit_engine_rpm: float | None = None,
        tire_circumference_m_override: float | None = None,
        units: JsonObject | None = None,
        amplitude_definitions: JsonObject | None = None,
        recorded_utc_offset_seconds: int | None = None,
    ) -> RunMetadata:
        """Construct canonical run metadata for a newly recorded run."""
        return cls(
            record_type=RUN_METADATA_TYPE,
            schema_version=RUN_SCHEMA_VERSION,
            run_id=run_id,
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
            sensor_model=sensor_model,
            firmware_version=firmware_version,
            raw_sample_rate_hz=raw_sample_rate_hz,
            feature_interval_s=feature_interval_s,
            fft_window_size_samples=fft_window_size_samples,
            fft_window_type=FFT_WINDOW_TYPE,
            peak_picker_method=PEAK_PICKER_METHOD,
            accel_scale_g_per_lsb=accel_scale_g_per_lsb,
            incomplete_for_order_analysis=bool(incomplete_for_order_analysis),
            analysis_settings=(
                analysis_settings if analysis_settings is not None else AnalysisSettingsSnapshot()
            ),
            car=car,
            case_id=case_id.strip(),
            sensor_mac=sensor_mac,
            summary_version=max(1, int(summary_version)),
            symptom=symptom,
            report_date=report_date,
            language=(str(language).strip().lower() or "en"),
            explicit_engine_rpm=explicit_engine_rpm,
            tire_circumference_m_override=tire_circumference_m_override,
            units=units,
            amplitude_definitions=amplitude_definitions,
            recorded_utc_offset_seconds=recorded_utc_offset_seconds,
        )

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
    def active_car_id(self) -> str | None:
        return self.car.car_id if self.car is not None else None

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        return order_reference_spec_from_snapshot(self.analysis_settings)

    @property
    def final_drive_ratio(self) -> float | None:
        value = self.analysis_settings.final_drive_ratio
        return value if value > 0 else None

    @property
    def current_gear_ratio(self) -> float | None:
        value = self.analysis_settings.current_gear_ratio
        return value if value > 0 else None

    def order_reference_spec_for(
        self,
        sample: object | None = None,
    ) -> OrderReferenceSpec | None:
        spec = self.order_reference_spec
        if sample is None or spec is None:
            return spec
        final_drive = getattr(sample, "final_drive_ratio", None)
        gear_ratio = getattr(sample, "gear", None)
        if final_drive is None and gear_ratio is None:
            return spec
        return replace(
            spec,
            final_drive_ratio=final_drive if final_drive is not None else spec.final_drive_ratio,
            current_gear_ratio=gear_ratio if gear_ratio is not None else spec.current_gear_ratio,
        )

    @property
    def tire_circumference_m(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.supports_wheel_reference:
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
            and spec.is_complete
            and (self.explicit_engine_rpm is not None or spec.has_engine_reference)
        )
