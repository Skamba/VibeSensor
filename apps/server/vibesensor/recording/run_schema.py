"""Shared JSONL run-schema constants and canonical typed metadata contract."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from vibesensor.common.json_types import JsonObject
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.car import CarOrderReferenceStatus
from vibesensor.domain.diagnostic_case import Symptom
from vibesensor.domain.order_reference import OrderReferenceSpec
from vibesensor.domain.vehicle_configuration import VehicleFuelType
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.settings.order_reference_settings import order_reference_spec_from_snapshot

__all__ = [
    "FFT_WINDOW_TYPE",
    "GUIDED_PHASES",
    "GuidedPhaseName",
    "RunGuidedPhase",
    "PEAK_PICKER_METHOD",
    "RawCaptureFinalizeStatus",
    "RUN_METADATA_TYPE",
    "RUN_SCHEMA_VERSION",
    "RunRawCaptureFinalize",
    "RunFinalizationStageResult",
    "RunFinalizationStageStatus",
    "RunMetadata",
    "RunCarMetadata",
    "RunSensorMetadata",
]

RUN_SCHEMA_VERSION = "v2-jsonl"
RUN_METADATA_TYPE = "run_metadata"
FFT_WINDOW_TYPE = "hann"
PEAK_PICKER_METHOD = "canonical_strength_metrics_module"

type RawCaptureFinalizeStatus = Literal[
    "completed",
    "not_configured",
    "enqueue_timeout",
    "timeout",
    "failed",
]

_DEGRADED_RAW_CAPTURE_FINALIZE_STATUSES = frozenset({"enqueue_timeout", "timeout", "failed"})


@dataclass(frozen=True, slots=True)
class RunCarMetadata:
    """Minimal run-attached car identity stored alongside analysis settings."""

    car_id: str | None = None
    name: str | None = None
    car_type: str | None = None
    variant: str | None = None
    order_reference_status: CarOrderReferenceStatus | None = None
    fuel_type: VehicleFuelType | None = None


@dataclass(frozen=True, slots=True)
class RunSensorMetadata:
    """Stable per-run snapshot of sensor identity and presentation metadata."""

    sensor_id: str
    display_name: str = ""
    location_code: str = ""
    mount_orientation: str | None = None
    sample_rate_hz: int | None = None
    firmware_version: str | None = None


@dataclass(frozen=True, slots=True)
class RunRawCaptureFinalize:
    """Persisted per-run raw-capture finalization outcome."""

    status: RawCaptureFinalizeStatus
    queue_depth: int | None = None
    error_summary: str | None = None

    @property
    def degraded(self) -> bool:
        return self.status in _DEGRADED_RAW_CAPTURE_FINALIZE_STATUSES

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {"status": self.status}
        if self.queue_depth is not None:
            payload["queue_depth"] = self.queue_depth
        if self.error_summary is not None:
            payload["error_summary"] = self.error_summary
        return payload


type RunFinalizationStageStatus = Literal["ok", "skipped", "degraded", "failed"]


@dataclass(frozen=True, slots=True)
class RunFinalizationStageResult:
    """Persisted per-run recorder finalization stage outcome."""

    stage_name: str
    status: RunFinalizationStageStatus
    duration_ms: int
    artifacts_created: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostic_context: JsonObject = field(default_factory=dict)

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "stage_name": self.stage_name,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }
        if self.artifacts_created:
            payload["artifacts_created"] = list(self.artifacts_created)
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        if self.diagnostic_context:
            payload["diagnostic_context"] = self.diagnostic_context
        return payload


type GuidedPhaseName = Literal["sweep", "hold", "coast_down"]
GUIDED_PHASES: tuple[GuidedPhaseName, ...] = ("sweep", "hold", "coast_down")


@dataclass(frozen=True, slots=True)
class RunGuidedPhase:
    """One step of the optional guided test drive on the run's sample clock (``t_s``).

    ``end_t_s`` is ``None`` while the step is open; it then lasts until the run ends.
    """

    phase: GuidedPhaseName
    start_t_s: float
    end_t_s: float | None = None

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {"phase": self.phase, "start_t_s": self.start_t_s}
        if self.end_t_s is not None:
            payload["end_t_s"] = self.end_t_s
        return payload


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
    strength_algorithm_version: str | None
    peak_detector_version: str | None
    calibration_profile_id: str | None
    vehicle_baseline_profile_id: str | None
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
    sensor_snapshots: tuple[RunSensorMetadata, ...] = field(default_factory=tuple)
    raw_capture_finalize: RunRawCaptureFinalize | None = None
    finalization_stages: tuple[RunFinalizationStageResult, ...] = field(default_factory=tuple)
    case_id: str = ""
    sensor_mac: str | None = None
    symptom: Symptom | None = None
    report_date: str | None = None
    language: str = "en"
    wheel_circumference_m: float | None = None
    recorded_utc_offset_seconds: int | None = None
    guided_phases: tuple[RunGuidedPhase, ...] = field(default_factory=tuple)
    # The run started before the Pi clock was set (no NTP, no browser report), so
    # its start and end times are wrong; its duration is not.
    start_time_unverified: bool = False

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
        strength_algorithm_version: str | None = None,
        peak_detector_version: str | None = None,
        calibration_profile_id: str | None = None,
        vehicle_baseline_profile_id: str | None = None,
        end_time_utc: str | None = None,
        incomplete_for_order_analysis: bool = False,
        configured_raw_sample_rate_hz: int | None = None,
        analysis_settings: AnalysisSettingsSnapshot | None = None,
        car: RunCarMetadata | None = None,
        sensor_snapshots: tuple[RunSensorMetadata, ...] = (),
        raw_capture_finalize: RunRawCaptureFinalize | None = None,
        finalization_stages: tuple[RunFinalizationStageResult, ...] = (),
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
            strength_algorithm_version=strength_algorithm_version,
            peak_detector_version=peak_detector_version,
            calibration_profile_id=calibration_profile_id,
            vehicle_baseline_profile_id=vehicle_baseline_profile_id,
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
            sensor_snapshots=tuple(sensor_snapshots),
            raw_capture_finalize=raw_capture_finalize,
            finalization_stages=tuple(finalization_stages),
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
    def fuel_type(self) -> VehicleFuelType | None:
        """The car's powertrain (ICE/PHEV/EV); ``None`` when it is not known."""
        return self.car.fuel_type if self.car is not None else None

    @property
    def electric(self) -> bool:
        """A battery-electric car: no engine, and the motor turns with the wheels."""
        return self.fuel_type == "EV"

    def sensor_snapshot_for(self, sensor_id: str) -> RunSensorMetadata | None:
        normalized_sensor_id = str(sensor_id).strip()
        if not normalized_sensor_id:
            return None
        for snapshot in self.sensor_snapshots:
            if snapshot.sensor_id == normalized_sensor_id:
                return snapshot
        return None

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
            # An EV's motor turns at the driveshaft order; it has no engine order.
            and (
                spec.supports_driveshaft_reference
                if self.electric
                else spec.supports_engine_reference
            )
        )
