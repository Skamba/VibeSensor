"""Pure functions for building typed run metadata records."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import CarSnapshot
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.ports import ClientTracker
from vibesensor.shared.time_utils import coerce_utc_offset_seconds
from vibesensor.shared.types.run_schema import RunMetadata

from .run_context import build_run_context_snapshot, order_reference_context_complete


def firmware_version_for_run(registry: ClientTracker) -> str | None:
    """Collect firmware version string(s) from active clients."""
    versions: set[str] = set()
    for client_id in registry.active_client_ids():
        record = registry.get(client_id)
        if record is None:
            continue
        firmware_version = str(getattr(record, "firmware_version", "") or "").strip()
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
    recorded_utc_offset_seconds: int | None = None,
) -> RunMetadata:
    """Build and return typed run metadata from the supplied fields."""
    normalized_offset = coerce_utc_offset_seconds(recorded_utc_offset_seconds)
    return RunMetadata.create(
        run_id=run_id,
        start_time_utc=start_time_utc,
        sensor_model=sensor_model,
        firmware_version=firmware_version,
        raw_sample_rate_hz=raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=fft_window_size_samples,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        end_time_utc=end_time_utc,
        incomplete_for_order_analysis=incomplete_for_order_analysis,
        recorded_utc_offset_seconds=normalized_offset,
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
    language_provider: Callable[[], str] | None = None,
    recorded_utc_offset_seconds: int | None = None,
) -> RunMetadata:
    """Assemble comprehensive typed run metadata."""
    feature_interval_s = 1.0 / max(1.0, float(metrics_log_hz))
    raw_sample_rate_hz = default_sample_rate_hz if default_sample_rate_hz > 0 else None
    incomplete = raw_sample_rate_hz is None
    run_car_snapshot = _car_snapshot_for_run(
        active_car_snapshot=active_car_snapshot,
        firmware_version=firmware_version,
    )
    metadata = create_run_metadata(
        run_id=run_id,
        start_time_utc=start_time_utc,
        sensor_model=sensor_model,
        firmware_version=firmware_version,
        raw_sample_rate_hz=raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=(fft_window_size_samples if fft_window_size_samples > 0 else None),
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        incomplete_for_order_analysis=incomplete,
        recorded_utc_offset_seconds=recorded_utc_offset_seconds,
    )
    metadata.run_context = build_run_context_snapshot(
        analysis_settings_snapshot=analysis_settings_snapshot,
        active_car_snapshot=run_car_snapshot,
    )
    metadata.incomplete_for_order_analysis = not order_reference_context_complete(metadata)
    if language_provider is not None:
        metadata.language = str(language_provider()).strip().lower() or "en"
    return metadata


_SIMULATOR_DEFAULT_CAR = CarSnapshot(
    car_id="simulator-default",
    name="VibeSensor Simulator",
    car_type="sedan",
)


def _car_snapshot_for_run(
    *,
    active_car_snapshot: CarSnapshot | None,
    firmware_version: str | None,
) -> CarSnapshot | None:
    """Return the car snapshot to persist for a run."""
    if active_car_snapshot is not None:
        return active_car_snapshot
    tokens = [token.strip().lower() for token in str(firmware_version or "").split(",")]
    if any(token.startswith("sim-") for token in tokens if token):
        return _SIMULATOR_DEFAULT_CAR
    return None
