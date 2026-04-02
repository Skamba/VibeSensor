"""Pure functions for building canonical typed sensor frames from live sensor metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.strength_metrics import StrengthMetrics
from vibesensor.shared.boundaries.strength_metrics_codec import strength_metrics_from_mapping
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import MPS_TO_KMH
from vibesensor.shared.ports import ClientTracker, SensorMetadataReader
from vibesensor.shared.sensor_metadata import resolve_sensor_presentation
from vibesensor.shared.types.payload_types import ClientMetrics
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.strength_bands import bucket_for_strength

if TYPE_CHECKING:
    from vibesensor.shared.ports import SignalSource


_SPEED_SOURCE_MAP = {
    "manual": "manual",
    "gps": "gps",
    "obd2": "obd2",
    "fallback_manual": "manual",
    "none": "none",
}

_LIVE_SAMPLE_WINDOW_S = 2.0


def extract_strength_data(
    metrics: ClientMetrics,
) -> StrengthMetrics:
    """Extract strength metrics and top peaks from client metrics."""
    combined_metrics = metrics.get("combined")
    raw_strength_metrics = (
        combined_metrics.get("strength_metrics") if combined_metrics is not None else None
    )
    return strength_metrics_from_mapping(raw_strength_metrics)


def dominant_hz_from_strength(
    strength_metrics: StrengthMetrics,
) -> float | None:
    """Return the frequency of the strongest peak, or ``None``."""
    return strength_metrics.dominant_hz


class SpeedContext(NamedTuple):
    """Named result of :func:`resolve_speed_context`."""

    speed_kmh: float | None
    gps_speed_kmh: float | None
    speed_source: str
    engine_rpm: float | None
    engine_rpm_source: str


def resolve_speed_context(
    *,
    gps_speed_mps: float | None,
    resolved_speed_mps: float | None,
    resolved_speed_source: str,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    measured_engine_rpm: float | None = None,
    measured_engine_rpm_source: str | None = None,
) -> SpeedContext:
    """Resolve a concrete speed snapshot into sample-record values."""
    order_reference_spec = analysis_settings_snapshot.order_reference_spec
    gps_speed_kmh = (
        (float(gps_speed_mps) * MPS_TO_KMH) if isinstance(gps_speed_mps, NUMERIC_TYPES) else None
    )
    speed_kmh = (
        (float(resolved_speed_mps) * MPS_TO_KMH)
        if isinstance(resolved_speed_mps, NUMERIC_TYPES)
        else None
    )
    speed_source = _SPEED_SOURCE_MAP.get(resolved_speed_source, "none")
    engine_rpm_estimated = None
    if speed_kmh is not None and order_reference_spec is not None:
        engine_rpm_estimated = order_reference_spec.engine_rpm_from_speed_kmh(speed_kmh)
    measured_rpm = (
        float(measured_engine_rpm)
        if (
            isinstance(measured_engine_rpm, NUMERIC_TYPES)
            and not isinstance(measured_engine_rpm, bool)
        )
        else None
    )
    if measured_rpm is not None:
        engine_rpm = measured_rpm
        engine_rpm_source = str(measured_engine_rpm_source or "obd2")
    elif engine_rpm_estimated is not None:
        engine_rpm = engine_rpm_estimated
        engine_rpm_source = "estimated_from_speed_and_ratios"
    else:
        engine_rpm = None
        engine_rpm_source = "missing"

    return SpeedContext(
        speed_kmh=speed_kmh,
        gps_speed_kmh=gps_speed_kmh,
        speed_source=speed_source,
        engine_rpm=engine_rpm,
        engine_rpm_source=engine_rpm_source,
    )


def build_sample_records(
    *,
    run_id: str,
    t_s: float,
    timestamp_utc: str,
    registry: ClientTracker,
    processor: SignalSource,
    speed_context: SpeedContext,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    default_sample_rate_hz: int,
    sensor_metadata_reader: SensorMetadataReader | None = None,
    live_sample_window_s: float | None = _LIVE_SAMPLE_WINDOW_S,
) -> list[SensorFrame]:
    """Build one batch of typed sample records from all active clients."""
    (
        speed_kmh,
        gps_speed_kmh,
        speed_source,
        engine_rpm,
        engine_rpm_source,
    ) = speed_context
    order_reference_spec = analysis_settings_snapshot.order_reference_spec
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
        resolved_name, resolved_location = resolve_sensor_presentation(
            sensor_id=record.client_id,
            sensors_by_mac=sensors_by_mac,
            fallback_name=str(record.name or ""),
            fallback_location_code=str(getattr(record, "location_code", "") or ""),
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
            )
        )

    return records
