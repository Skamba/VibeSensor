"""Shared JSONL run-schema constants and canonical typed metadata contract."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from vibesensor.domain import AnalysisSettingsSnapshot, OrderReferenceSpec, Symptom
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot

from .sensor_frame import SensorFrame

__all__ = [
    "FFT_WINDOW_TYPE",
    "PEAK_PICKER_METHOD",
    "RUN_END_TYPE",
    "RUN_METADATA_TYPE",
    "RUN_SAMPLE_TYPE",
    "RUN_SCHEMA_VERSION",
    "RunMetadata",
    "RunCarMetadata",
]

RUN_SCHEMA_VERSION = "v2-jsonl"
RUN_METADATA_TYPE = "run_metadata"
RUN_SAMPLE_TYPE = "sample"
RUN_END_TYPE = "run_end"
FFT_WINDOW_TYPE = "hann"
PEAK_PICKER_METHOD = "canonical_strength_metrics_module"


@dataclass(frozen=True, slots=True)
class RunCarMetadata:
    """Minimal run-attached car identity stored alongside analysis settings."""

    car_id: str | None = None
    name: str | None = None
    car_type: str | None = None
    variant: str | None = None


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
    configured_raw_sample_rate_hz: int | None
    feature_interval_s: float | None
    fft_window_size_samples: int | None
    fft_window_type: str | None
    peak_picker_method: str
    accel_scale_g_per_lsb: float | None
    incomplete_for_order_analysis: bool
    analysis_settings: AnalysisSettingsSnapshot = field(default_factory=AnalysisSettingsSnapshot)
    car: RunCarMetadata | None = None
    case_id: str = ""
    sensor_mac: str | None = None
    symptom: Symptom | None = None
    report_date: str | None = None
    language: str = "en"
    wheel_circumference_m: float | None = None
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
        configured_raw_sample_rate_hz: int | None = None,
        analysis_settings: AnalysisSettingsSnapshot | None = None,
        car: RunCarMetadata | None = None,
        case_id: str = "",
        sensor_mac: str | None = None,
        symptom: Symptom | None = None,
        report_date: str | None = None,
        language: str = "en",
        wheel_circumference_m: float | None = None,
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
            configured_raw_sample_rate_hz=configured_raw_sample_rate_hz,
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
            symptom=symptom,
            report_date=report_date,
            language=(str(language).strip().lower() or "en"),
            wheel_circumference_m=wheel_circumference_m,
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
    def tire_circumference_m(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.supports_wheel_reference:
            return spec.tire_circumference_m
        if self.wheel_circumference_m is not None and self.wheel_circumference_m > 0:
            return self.wheel_circumference_m
        return None

    @property
    def reference_complete(self) -> bool:
        spec = self.order_reference_spec
        return bool(
            self.raw_sample_rate_hz
            and self.tire_circumference_m
            and spec is not None
            and spec.is_complete
            and spec.has_engine_reference
        )
