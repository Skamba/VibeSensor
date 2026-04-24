"""Pure functions for building canonical typed sensor frames from live sensor metrics."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot
from vibesensor.shared.sensor_metadata import resolve_sensor_presentation
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.strength_bands import bucket_for_strength

from .sample_speed_context import SpeedContext, resolve_speed_context_snapshot
from .sample_strength_metrics import dominant_hz_from_strength, extract_strength_data

if TYPE_CHECKING:
    from vibesensor.shared.ports import (
        ClientTracker,
        SensorMetadataReader,
        SignalSource,
        SpeedProvider,
    )


_LIVE_SAMPLE_WINDOW_S = 2.0


def build_sample_records(
    *,
    run_id: str,
    t_s: float,
    timestamp_utc: str,
    registry: ClientTracker,
    processor: SignalSource,
    speed_context: SpeedContext,
    speed_provider: SpeedProvider | None = None,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    default_sample_rate_hz: int,
    sensor_metadata_reader: SensorMetadataReader | None = None,
    run_sensor_presentation_resolver: Callable[..., tuple[str, str]] | None = None,
    live_sample_window_s: float | None = _LIVE_SAMPLE_WINDOW_S,
    run_start_mono_s: float | None = None,
) -> list[SensorFrame]:
    """Build one batch of typed sample records from all active clients."""

    order_reference_spec = order_reference_spec_from_snapshot(analysis_settings_snapshot)
    final_drive_ratio = (
        order_reference_spec.final_drive_ratio if order_reference_spec is not None else None
    )
    gear_ratio = (
        order_reference_spec.current_gear_ratio if order_reference_spec is not None else None
    )
    sensors_by_mac = sensor_metadata_reader.get_sensors() if sensor_metadata_reader else {}

    records: list[SensorFrame] = []
    registry_client_ids = registry.active_client_ids()
    if live_sample_window_s is None:
        active_client_ids = sorted(set(registry_client_ids))
    else:
        active_client_ids = sorted(
            set(
                processor.clients_with_recent_data(
                    registry_client_ids,
                    max_age_s=live_sample_window_s,
                ),
            ),
        )
    for client_id in active_client_ids:
        record = registry.get(client_id)
        if record is None:
            continue
        metrics = processor.latest_metrics(client_id)
        if not metrics:
            continue

        latest_xyz = processor.latest_sample_xyz(record.client_id)
        accel_x_g = latest_xyz[0] if latest_xyz else None
        accel_y_g = latest_xyz[1] if latest_xyz else None
        accel_z_g = latest_xyz[2] if latest_xyz else None

        strength_metrics = extract_strength_data(metrics)
        dominant_hz = dominant_hz_from_strength(strength_metrics)
        vibration_strength_db = strength_metrics.vibration_strength_db
        strength_peak_amp_g = strength_metrics.peak_amp_g
        strength_floor_amp_g = strength_metrics.noise_floor_amp_g
        strength_bucket = (
            bucket_for_strength(vibration_strength_db)
            if vibration_strength_db is not None
            else None
        )

        sample_rate_hz = (
            processor.latest_sample_rate_hz(record.client_id)
            or int(record.sample_rate_hz or 0)
            or default_sample_rate_hz
            or None
        )
        fallback_name = str(record.name or "")
        fallback_location_code = str(getattr(record, "location_code", "") or "")
        if run_sensor_presentation_resolver is None:
            resolved_name, resolved_location = resolve_sensor_presentation(
                sensor_id=record.client_id,
                sensors_by_mac=sensors_by_mac,
                fallback_name=fallback_name,
                fallback_location_code=fallback_location_code,
            )
        else:
            resolved_name, resolved_location = run_sensor_presentation_resolver(
                client_id=record.client_id,
                fallback_name=fallback_name,
                fallback_location_code=fallback_location_code,
                sample_rate_hz=int(sample_rate_hz) if sample_rate_hz else None,
                firmware_version=str(getattr(record, "firmware_version", "") or "") or None,
                sensors_by_mac=sensors_by_mac,
            )
        (
            analysis_window_start_us,
            analysis_window_end_us,
            analysis_window_synced,
            analysis_time_range,
        ) = _analysis_window_fields(
            processor=processor,
            client_id=record.client_id,
            run_start_mono_s=run_start_mono_s,
        )
        (
            speed_kmh,
            gps_speed_kmh,
            speed_source,
            engine_rpm,
            engine_rpm_source,
        ) = _speed_context_for_record(
            fallback_speed_context=speed_context,
            speed_provider=speed_provider,
            analysis_settings_snapshot=analysis_settings_snapshot,
            analysis_time_range=analysis_time_range,
            run_start_mono_s=run_start_mono_s,
        )
        records.append(
            SensorFrame(
                run_id=run_id,
                timestamp_utc=timestamp_utc,
                t_s=t_s,
                client_id=client_id,
                client_name=resolved_name,
                location=resolved_location,
                sample_rate_hz=int(sample_rate_hz) if sample_rate_hz else None,
                speed_kmh=speed_kmh,
                gps_speed_kmh=gps_speed_kmh,
                speed_source=speed_source,
                engine_rpm=engine_rpm,
                engine_rpm_source=engine_rpm_source,
                gear=gear_ratio if isinstance(gear_ratio, float) else None,
                final_drive_ratio=(
                    final_drive_ratio if isinstance(final_drive_ratio, float) else None
                ),
                accel_x_g=accel_x_g,
                accel_y_g=accel_y_g,
                accel_z_g=accel_z_g,
                dominant_freq_hz=dominant_hz,
                dominant_axis="combined",
                top_peaks=tuple(peak for peak in strength_metrics.top_peaks[:8] if peak.is_valid),
                vibration_strength_db=vibration_strength_db,
                strength_bucket=strength_bucket,
                strength_peak_amp_g=strength_peak_amp_g,
                strength_floor_amp_g=strength_floor_amp_g,
                frames_dropped_total=int(record.frames_dropped),
                queue_overflow_drops=int(record.queue_overflow_drops),
                analysis_window_start_us=analysis_window_start_us,
                analysis_window_end_us=analysis_window_end_us,
                analysis_window_synced=analysis_window_synced,
            )
        )

    return records


def _analysis_window_fields(
    *,
    processor: SignalSource,
    client_id: str,
    run_start_mono_s: float | None,
) -> tuple[int | None, int | None, bool | None, AnalysisTimeRange | None]:
    if run_start_mono_s is None:
        return None, None, None, None
    time_range = processor.latest_analysis_time_range(client_id)
    if time_range is None:
        return None, None, None, None
    return (
        int(round((time_range.start_s - run_start_mono_s) * 1_000_000.0)),
        int(round((time_range.end_s - run_start_mono_s) * 1_000_000.0)),
        bool(time_range.synced),
        time_range,
    )


def _speed_context_for_record(
    *,
    fallback_speed_context: SpeedContext,
    speed_provider: SpeedProvider | None,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    analysis_time_range: AnalysisTimeRange | None,
    run_start_mono_s: float | None,
) -> SpeedContext:
    if speed_provider is None or run_start_mono_s is None:
        return fallback_speed_context
    target_mono_s = None
    if analysis_time_range is not None:
        target_mono_s = analysis_time_range.start_s + (
            (analysis_time_range.end_s - analysis_time_range.start_s) / 2.0
        )
    return resolve_speed_context_snapshot(
        snapshot=speed_provider.resolve_speed_context_at(target_mono_s),
        analysis_settings_snapshot=analysis_settings_snapshot,
    )
