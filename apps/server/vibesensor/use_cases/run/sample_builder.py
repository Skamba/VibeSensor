"""Pure functions for building sample records from sensor metrics.

All functions in this module are stateless and can be tested independently
of ``RunRecorder`` or any async / threading machinery.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, NamedTuple

from vibesensor.adapters.udp.protocol import SensorFrame
from vibesensor.domain.car import CarSnapshot
from vibesensor.domain.strength_metrics import StrengthMetrics
from vibesensor.domain.snapshots import AnalysisSettingsSnapshot
from vibesensor.infra.config.analysis_settings import (
    engine_rpm_from_wheel_hz,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from vibesensor.shared.constants import MPS_TO_KMH, NUMERIC_TYPES
from vibesensor.shared.run_context import (
    apply_run_context_snapshot,
    order_reference_context_complete,
)
from vibesensor.strength_bands import bucket_for_strength

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry

_isfinite = math.isfinite

def _safe_float(d: Mapping[str, object], key: str) -> float | None:
    """Extract a finite float from *d[key]*, or ``None``."""
    raw = d.get(key)
    if raw is None:
        return None
    try:
        out = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if _isfinite(out) else None


_SPEED_SOURCE_MAP = {
    "manual": "manual",
    "gps": "gps",
    "fallback_manual": "manual",
    "none": "none",
}


def safe_metric(metrics: dict[str, object], axis: str, key: str) -> float | None:
    """Extract a single numeric metric, returning ``None`` for missing/invalid."""
    axis_metrics = metrics.get(axis)
    if not isinstance(axis_metrics, dict):
        return None
    return _safe_float(axis_metrics, key)


class StrengthExtraction(NamedTuple):
    """Named result of :func:`extract_strength_data`."""

    strength_metrics: StrengthMetrics
    top_peaks: list[dict[str, object]]


def _raw_strength_metrics(metrics: Mapping[str, object]) -> Mapping[str, object] | None:
    combined = metrics.get("combined")
    if not isinstance(combined, Mapping):
        return None
    nested = combined.get("strength_metrics")
    return nested if isinstance(nested, Mapping) else None


def extract_strength_data(
    metrics: Mapping[str, object],
) -> StrengthExtraction:
    """Extract strength metrics and top peaks from client metrics."""
    raw_strength_metrics = _raw_strength_metrics(metrics)
    strength_metrics = (
        StrengthMetrics.from_typed_dict(raw_strength_metrics)
        if raw_strength_metrics is not None
        else StrengthMetrics()
    )

    return StrengthExtraction(
        strength_metrics=strength_metrics,
        top_peaks=strength_metrics.to_peak_payloads(max_items=8),
    )


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
    engine_rpm_estimated: float | None


def resolve_speed_context(
    gps_monitor: GPSSpeedMonitor,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
) -> SpeedContext:
    """Resolve current speed/vehicle state into sample-record values."""
    s = analysis_settings_snapshot
    tire_circumference_m = tire_circumference_m_from_spec(
        s.tire_width_mm or None,
        s.tire_aspect_pct or None,
        s.rim_in or None,
        deflection_factor=s.tire_deflection_factor or None,
    )
    final_drive_ratio = s.final_drive_ratio or None
    gear_ratio = s.current_gear_ratio or None
    gps_speed_mps = gps_monitor.speed_mps
    resolution = gps_monitor.resolve_speed()
    effective_speed_mps = resolution.speed_mps
    gps_speed_kmh = (
        (float(gps_speed_mps) * MPS_TO_KMH) if isinstance(gps_speed_mps, NUMERIC_TYPES) else None
    )
    speed_kmh = (
        (float(effective_speed_mps) * MPS_TO_KMH)
        if isinstance(effective_speed_mps, NUMERIC_TYPES)
        else None
    )
    speed_source = _SPEED_SOURCE_MAP.get(resolution.source, "none")
    engine_rpm_estimated = None
    if (
        speed_kmh is not None
        and tire_circumference_m is not None
        and tire_circumference_m > 0
        and isinstance(final_drive_ratio, float)
        and final_drive_ratio > 0
        and isinstance(gear_ratio, float)
        and gear_ratio > 0
    ):
        whz = wheel_hz_from_speed_kmh(speed_kmh, tire_circumference_m)
        if whz is not None:
            engine_rpm_estimated = engine_rpm_from_wheel_hz(whz, final_drive_ratio, gear_ratio)

    return SpeedContext(
        speed_kmh=speed_kmh,
        gps_speed_kmh=gps_speed_kmh,
        speed_source=speed_source,
        engine_rpm_estimated=engine_rpm_estimated,
    )


def firmware_version_for_run(registry: ClientRegistry) -> str | None:
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


_LIVE_SAMPLE_WINDOW_S = 2.0


def build_sample_records(
    *,
    run_id: str,
    t_s: float,
    timestamp_utc: str,
    registry: ClientRegistry,
    processor: SignalProcessor,
    gps_monitor: GPSSpeedMonitor,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    default_sample_rate_hz: int,
) -> list[dict[str, object]]:
    """Build one batch of sample records from all active clients."""
    (
        speed_kmh,
        gps_speed_kmh,
        speed_source,
        engine_rpm_estimated,
    ) = resolve_speed_context(gps_monitor, analysis_settings_snapshot)
    final_drive_ratio = analysis_settings_snapshot.final_drive_ratio or None
    gear_ratio = analysis_settings_snapshot.current_gear_ratio or None

    records: list[dict[str, object]] = []
    active_client_ids = sorted(
        set(
            processor.clients_with_recent_data(
                registry.active_client_ids(),
                max_age_s=_LIVE_SAMPLE_WINDOW_S,
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

        (
            strength_metrics,
            top_peaks,
        ) = extract_strength_data(metrics)
        dominant_hz = dominant_hz_from_strength(strength_metrics)
        vibration_strength_db = strength_metrics.vibration_strength_db
        strength_peak_amp_g = strength_metrics.peak_amp_g
        strength_floor_amp_g = strength_metrics.noise_floor_amp_g

        # Derive severity bucket directly from the dB value via the
        # canonical bucket_for_strength() function (single source of truth).
        strength_bucket: str | None = None
        if vibration_strength_db is not None:
            strength_bucket = bucket_for_strength(vibration_strength_db)

        sample_rate_hz = (
            processor.latest_sample_rate_hz(record.client_id)
            or int(record.sample_rate_hz or 0)
            or default_sample_rate_hz
            or None
        )
        frame = SensorFrame(
            run_id=run_id,
            timestamp_utc=timestamp_utc,
            t_s=t_s,
            client_id=client_id,
            client_name=record.name,
            location=str(getattr(record, "location_code", "") or ""),
            sample_rate_hz=int(sample_rate_hz) if sample_rate_hz else None,
            speed_kmh=speed_kmh,
            gps_speed_kmh=gps_speed_kmh,
            speed_source=speed_source,
            engine_rpm=engine_rpm_estimated,
            engine_rpm_source=(
                "estimated_from_speed_and_ratios" if engine_rpm_estimated is not None else "missing"
            ),
            gear=gear_ratio if isinstance(gear_ratio, float) else None,
            final_drive_ratio=final_drive_ratio if isinstance(final_drive_ratio, float) else None,
            accel_x_g=accel_x_g,
            accel_y_g=accel_y_g,
            accel_z_g=accel_z_g,
            dominant_freq_hz=dominant_hz,
            dominant_axis="combined",
            top_peaks=top_peaks,
            vibration_strength_db=vibration_strength_db,
            strength_bucket=strength_bucket,
            strength_peak_amp_g=strength_peak_amp_g,
            strength_floor_amp_g=strength_floor_amp_g,
            frames_dropped_total=int(record.frames_dropped),
            queue_overflow_drops=int(record.queue_overflow_drops),
        )
        records.append(frame.to_dict())

    return records


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
) -> dict[str, object]:
    """Assemble comprehensive run metadata."""
    from vibesensor.adapters.persistence.runlog import create_run_metadata

    settings = asdict(analysis_settings_snapshot)
    feature_interval_s = 1.0 / max(1.0, float(metrics_log_hz))
    raw_sample_rate_hz = default_sample_rate_hz if default_sample_rate_hz > 0 else None
    incomplete = raw_sample_rate_hz is None
    metadata = create_run_metadata(
        run_id=run_id,
        start_time_utc=start_time_utc,
        sensor_model=sensor_model,
        firmware_version=firmware_version,
        raw_sample_rate_hz=raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=fft_window_size_samples if fft_window_size_samples > 0 else None,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        incomplete_for_order_analysis=incomplete,
    )
    metadata.update(settings)
    metadata["tire_circumference_m"] = tire_circumference_m_from_spec(
        analysis_settings_snapshot.tire_width_mm,
        analysis_settings_snapshot.tire_aspect_pct,
        analysis_settings_snapshot.rim_in,
        deflection_factor=analysis_settings_snapshot.tire_deflection_factor,
    )
    apply_run_context_snapshot(
        metadata,
        analysis_settings_snapshot=analysis_settings_snapshot,
        active_car_snapshot=active_car_snapshot,
    )
    metadata["incomplete_for_order_analysis"] = not order_reference_context_complete(metadata)
    if language_provider is not None:
        metadata["language"] = str(language_provider()).strip().lower() or "en"
    return dict(metadata)
