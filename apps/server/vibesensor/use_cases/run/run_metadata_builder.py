"""Pure functions for building typed run metadata records."""

from __future__ import annotations

from vibesensor.domain import CarSnapshot
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.ports import ClientTracker, LanguageReader
from vibesensor.shared.time_utils import coerce_utc_offset_seconds
from vibesensor.shared.types.raw_capture import RawCaptureManifest
from vibesensor.shared.types.run_schema import RunCarMetadata, RunMetadata, RunSensorMetadata

from .run_context import order_reference_context_complete


def firmware_version_for_run(registry: ClientTracker) -> str | None:
    """Collect firmware version string(s) from active clients."""
    versions: set[str] = set()
    for client_id in registry.active_client_ids():
        record = registry.get(client_id)
        if record is None:
            continue
        raw_firmware_version = record.firmware_version
        if raw_firmware_version is None:
            continue
        firmware_version = raw_firmware_version.strip()
        if firmware_version:
            versions.add(firmware_version)
    if not versions:
        return None
    if len(versions) == 1:
        return next(iter(versions))
    return ", ".join(sorted(versions))


def create_run_metadata(
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
    recorded_utc_offset_seconds: int | None = None,
    sensor_snapshots: tuple[RunSensorMetadata, ...] = (),
) -> RunMetadata:
    """Build and return typed run metadata from the supplied fields."""
    normalized_offset = coerce_utc_offset_seconds(recorded_utc_offset_seconds)
    return RunMetadata.create(
        run_id=run_id,
        start_time_utc=start_time_utc,
        sensor_model=sensor_model,
        firmware_version=firmware_version,
        raw_sample_rate_hz=raw_sample_rate_hz,
        configured_raw_sample_rate_hz=configured_raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=fft_window_size_samples,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        end_time_utc=end_time_utc,
        incomplete_for_order_analysis=incomplete_for_order_analysis,
        recorded_utc_offset_seconds=normalized_offset,
        sensor_snapshots=sensor_snapshots,
    )


def build_run_metadata(
    *,
    run_id: str,
    start_time_utc: str,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    sensor_model: str,
    firmware_version: str | None,
    default_sample_rate_hz: int,
    metrics_log_hz: int,
    fft_window_size_samples: int,
    accel_scale_g_per_lsb: float | None,
    active_car_snapshot: CarSnapshot | None = None,
    raw_capture_manifest: RawCaptureManifest | None = None,
    language_reader: LanguageReader | None = None,
    recorded_utc_offset_seconds: int | None = None,
    sensor_snapshots: tuple[RunSensorMetadata, ...] = (),
) -> RunMetadata:
    """Assemble comprehensive typed run metadata."""
    feature_interval_s = 1.0 / max(1.0, float(metrics_log_hz))
    configured_raw_sample_rate_hz = default_sample_rate_hz if default_sample_rate_hz > 0 else None
    raw_sample_rate_hz = _canonical_raw_sample_rate_hz(
        raw_capture_manifest,
        fallback_sample_rate_hz=configured_raw_sample_rate_hz,
    )
    incomplete = raw_sample_rate_hz is None
    run_car_metadata = _run_car_metadata_for_run(
        active_car_snapshot=active_car_snapshot,
        firmware_version=firmware_version,
    )
    metadata = create_run_metadata(
        run_id=run_id,
        start_time_utc=start_time_utc,
        sensor_model=sensor_model,
        firmware_version=firmware_version,
        raw_sample_rate_hz=raw_sample_rate_hz,
        configured_raw_sample_rate_hz=configured_raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=(fft_window_size_samples if fft_window_size_samples > 0 else None),
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        incomplete_for_order_analysis=incomplete,
        recorded_utc_offset_seconds=recorded_utc_offset_seconds,
        sensor_snapshots=sensor_snapshots,
    )
    metadata.analysis_settings = analysis_settings_snapshot
    metadata.car = run_car_metadata
    metadata.incomplete_for_order_analysis = not order_reference_context_complete(metadata)
    if language_reader is not None:
        metadata.language = str(language_reader.language).strip().lower() or "en"
    return metadata


def _canonical_raw_sample_rate_hz(
    raw_capture_manifest: RawCaptureManifest | None,
    *,
    fallback_sample_rate_hz: int | None,
) -> int | None:
    if raw_capture_manifest is None:
        return fallback_sample_rate_hz
    observed_rates_hz = {
        sensor.sample_rate_hz
        for sensor in raw_capture_manifest.sensors
        if sensor.sample_rate_hz > 0
    }
    if len(observed_rates_hz) == 1:
        return next(iter(observed_rates_hz))
    if len(observed_rates_hz) > 1:
        return None
    return fallback_sample_rate_hz


_SIMULATOR_DEFAULT_CAR = RunCarMetadata(
    car_id="simulator-default",
    name="VibeSensor Simulator",
    car_type="sedan",
)


def _run_car_metadata_for_run(
    *,
    active_car_snapshot: CarSnapshot | None,
    firmware_version: str | None,
) -> RunCarMetadata | None:
    """Return the minimal run-car metadata to persist for a run."""

    if active_car_snapshot is not None:
        return RunCarMetadata(
            car_id=active_car_snapshot.car_id,
            name=active_car_snapshot.name,
            car_type=active_car_snapshot.car_type,
            variant=active_car_snapshot.variant,
        )
    tokens = [token.strip().lower() for token in str(firmware_version or "").split(",")]
    if any(token.startswith("sim-") for token in tokens if token):
        return _SIMULATOR_DEFAULT_CAR
    return None
