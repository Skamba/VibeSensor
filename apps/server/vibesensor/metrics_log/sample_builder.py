"""Pure functions for building sample records from sensor metrics.

All functions in this module are stateless and can be tested independently
of ``MetricsLogger`` or any async / threading machinery.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from vibesensor_shared.contracts import METRIC_FIELDS

from ..analysis_settings import (
    engine_rpm_from_wheel_hz,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from ..constants import MPS_TO_KMH
from ..domain_models import SensorFrame

if TYPE_CHECKING:
    from ..gps_speed import GPSSpeedMonitor
    from ..processing import SignalProcessor
    from ..registry import ClientRegistry

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
    raw = axis_metrics.get(key)
    if raw is None:
        return None
    try:
        out = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def extract_strength_data(
    metrics: dict[str, object],
) -> tuple[
    dict[str, object],
    float | None,
    str | None,
    float | None,
    float | None,
    list[dict[str, object]],
]:
    """Extract strength metrics and top peaks from client metrics.

    Returns ``(strength_metrics, vibration_strength_db, strength_bucket,
    strength_peak_amp_g, strength_floor_amp_g, top_peaks)``.
    """
    strength_metrics: dict[str, object] = {}
    root_strength_metrics = metrics.get("strength_metrics")
    if isinstance(root_strength_metrics, dict):
        strength_metrics = root_strength_metrics
    elif isinstance(metrics.get("combined"), dict):
        nested_strength_metrics = metrics.get("combined", {}).get("strength_metrics")
        if isinstance(nested_strength_metrics, dict):
            strength_metrics = nested_strength_metrics

    vibration_strength_db = safe_metric(
        {"combined": strength_metrics}, "combined", METRIC_FIELDS["vibration_strength_db"]
    )
    strength_bucket = (
        str(strength_metrics.get(METRIC_FIELDS["strength_bucket"]))
        if strength_metrics.get(METRIC_FIELDS["strength_bucket"]) not in (None, "")
        else None
    )
    strength_peak_amp_g = safe_metric(
        {"combined": strength_metrics},
        "combined",
        "peak_amp_g",
    )
    strength_floor_amp_g = safe_metric(
        {"combined": strength_metrics},
        "combined",
        "noise_floor_amp_g",
    )

    top_peaks_raw = strength_metrics.get("top_peaks")
    top_peaks: list[dict[str, object]] = []
    if isinstance(top_peaks_raw, list):
        for peak in top_peaks_raw[:8]:
            if not isinstance(peak, dict):
                continue
            try:
                hz = float(peak.get("hz"))
                amp = float(peak.get("amp"))
            except (TypeError, ValueError):
                continue
            if (
                not math.isnan(hz)
                and not math.isnan(amp)
                and not math.isinf(hz)
                and not math.isinf(amp)
                and hz > 0
            ):
                peak_payload: dict[str, object] = {"hz": hz, "amp": amp}
                peak_db = safe_metric(
                    {"combined": peak},
                    "combined",
                    METRIC_FIELDS["vibration_strength_db"],
                )
                if peak_db is not None:
                    peak_payload[METRIC_FIELDS["vibration_strength_db"]] = peak_db
                peak_bucket = peak.get(METRIC_FIELDS["strength_bucket"])
                if peak_bucket not in (None, ""):
                    peak_payload[METRIC_FIELDS["strength_bucket"]] = str(peak_bucket)
                top_peaks.append(peak_payload)

    return (
        strength_metrics,
        vibration_strength_db,
        strength_bucket,
        strength_peak_amp_g,
        strength_floor_amp_g,
        top_peaks,
    )


def extract_axis_top_peaks(metrics: dict[str, object], axis: str) -> list[dict[str, object]]:
    """Return the top 3 peaks for a single axis."""
    axis_metrics = metrics.get(axis)
    if not isinstance(axis_metrics, dict):
        return []
    axis_peaks_raw = axis_metrics.get("peaks")
    axis_peaks: list[dict[str, object]] = []
    if isinstance(axis_peaks_raw, list):
        for peak in axis_peaks_raw[:3]:
            if not isinstance(peak, dict):
                continue
            try:
                hz = float(peak.get("hz"))
                amp = float(peak.get("amp"))
            except (TypeError, ValueError):
                continue
            if (
                not math.isnan(hz)
                and not math.isnan(amp)
                and not math.isinf(hz)
                and not math.isinf(amp)
                and hz > 0
            ):
                axis_peaks.append({"hz": hz, "amp": amp})
    return axis_peaks


def dominant_hz_from_strength(
    strength_metrics: dict[str, object],
) -> float | None:
    """Return the frequency of the strongest peak, or ``None``."""
    top_peaks_raw = strength_metrics.get("top_peaks")
    if isinstance(top_peaks_raw, list) and top_peaks_raw:
        first_peak = top_peaks_raw[0]
        if isinstance(first_peak, dict):
            return safe_metric({"combined": first_peak}, "combined", "hz")
    return None


def resolve_speed_context(
    gps_monitor: GPSSpeedMonitor,
    analysis_settings_snapshot: dict[str, object],
) -> tuple[float | None, float | None, str, float | None, float | None, float | None]:
    """Resolve current speed/vehicle state into sample-record values.

    Returns ``(speed_kmh, gps_speed_kmh, speed_source,
    engine_rpm_estimated, final_drive_ratio, gear_ratio)``.
    """
    settings = analysis_settings_snapshot
    tire_circumference_m = tire_circumference_m_from_spec(
        settings.get("tire_width_mm"),
        settings.get("tire_aspect_pct"),
        settings.get("rim_in"),
        deflection_factor=settings.get("tire_deflection_factor"),
    )
    final_drive_ratio = settings.get("final_drive_ratio")
    gear_ratio = settings.get("current_gear_ratio")
    gps_speed_mps = gps_monitor.speed_mps
    effective_speed_mps = gps_monitor.effective_speed_mps
    gps_speed_kmh = (
        (float(gps_speed_mps) * MPS_TO_KMH) if isinstance(gps_speed_mps, (int, float)) else None
    )
    speed_kmh = (
        (float(effective_speed_mps) * MPS_TO_KMH)
        if isinstance(effective_speed_mps, (int, float))
        else None
    )
    speed_source = _SPEED_SOURCE_MAP.get(gps_monitor.resolve_speed().source, "none")
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

    return (
        speed_kmh,
        gps_speed_kmh,
        speed_source,
        engine_rpm_estimated,
        final_drive_ratio,
        gear_ratio,
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
    analysis_settings_snapshot: dict[str, object],
    default_sample_rate_hz: int,
) -> list[dict[str, object]]:
    """Build one batch of sample records from all active clients."""
    (
        speed_kmh,
        gps_speed_kmh,
        speed_source,
        engine_rpm_estimated,
        final_drive_ratio,
        gear_ratio,
    ) = resolve_speed_context(gps_monitor, analysis_settings_snapshot)

    records: list[dict[str, object]] = []
    active_client_ids = sorted(
        set(
            processor.clients_with_recent_data(
                registry.active_client_ids(), max_age_s=_LIVE_SAMPLE_WINDOW_S
            )
        )
    )
    for client_id in active_client_ids:
        record = registry.get(client_id)
        if record is None:
            continue
        metrics = record.latest_metrics
        if not metrics:
            continue

        latest_xyz = processor.latest_sample_xyz(record.client_id)
        accel_x_g = latest_xyz[0] if latest_xyz else None
        accel_y_g = latest_xyz[1] if latest_xyz else None
        accel_z_g = latest_xyz[2] if latest_xyz else None

        (
            strength_metrics,
            vibration_strength_db,
            strength_bucket,
            strength_peak_amp_g,
            strength_floor_amp_g,
            top_peaks,
        ) = extract_strength_data(metrics)
        top_peaks_x = extract_axis_top_peaks(metrics, "x")
        top_peaks_y = extract_axis_top_peaks(metrics, "y")
        top_peaks_z = extract_axis_top_peaks(metrics, "z")
        dominant_hz = dominant_hz_from_strength(strength_metrics)

        sample_rate_hz = (
            processor.latest_sample_rate_hz(record.client_id)
            or int(record.sample_rate_hz or 0)
            or default_sample_rate_hz
            or None
        )
        frame = SensorFrame(
            record_type="sample",
            schema_version="v2-jsonl",
            run_id=run_id,
            timestamp_utc=timestamp_utc,
            t_s=t_s,
            client_id=client_id,
            client_name=record.name,
            location=str(getattr(record, "location", "") or ""),
            sample_rate_hz=int(sample_rate_hz) if sample_rate_hz else None,
            speed_kmh=speed_kmh,
            gps_speed_kmh=gps_speed_kmh,
            speed_source=speed_source,
            engine_rpm=engine_rpm_estimated,
            engine_rpm_source=(
                "estimated_from_speed_and_ratios"
                if engine_rpm_estimated is not None
                else "missing"
            ),
            gear=gear_ratio if isinstance(gear_ratio, float) else None,
            final_drive_ratio=final_drive_ratio
            if isinstance(final_drive_ratio, float)
            else None,
            accel_x_g=accel_x_g,
            accel_y_g=accel_y_g,
            accel_z_g=accel_z_g,
            dominant_freq_hz=dominant_hz,
            dominant_axis="combined",
            top_peaks=top_peaks,
            top_peaks_x=top_peaks_x,
            top_peaks_y=top_peaks_y,
            top_peaks_z=top_peaks_z,
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
    analysis_settings_snapshot: dict[str, object],
    sensor_model: str,
    firmware_version: str | None,
    default_sample_rate_hz: int,
    metrics_log_hz: int,
    fft_window_size_samples: int,
    fft_window_type: str,
    peak_picker_method: str,
    accel_scale_g_per_lsb: float | None,
    language_provider: object | None = None,
) -> dict[str, object]:
    """Assemble comprehensive run metadata."""
    from ..runlog import create_run_metadata

    settings = analysis_settings_snapshot
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
        fft_window_size_samples=fft_window_size_samples
        if fft_window_size_samples > 0
        else None,
        fft_window_type=fft_window_type or None,
        peak_picker_method=peak_picker_method,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        incomplete_for_order_analysis=incomplete,
    )
    metadata.update(
        {
            "tire_width_mm": settings.get("tire_width_mm"),
            "tire_aspect_pct": settings.get("tire_aspect_pct"),
            "rim_in": settings.get("rim_in"),
            "final_drive_ratio": settings.get("final_drive_ratio"),
            "current_gear_ratio": settings.get("current_gear_ratio"),
            "wheel_bandwidth_pct": settings.get("wheel_bandwidth_pct"),
            "driveshaft_bandwidth_pct": settings.get("driveshaft_bandwidth_pct"),
            "engine_bandwidth_pct": settings.get("engine_bandwidth_pct"),
            "speed_uncertainty_pct": settings.get("speed_uncertainty_pct"),
            "tire_diameter_uncertainty_pct": settings.get("tire_diameter_uncertainty_pct"),
            "final_drive_uncertainty_pct": settings.get("final_drive_uncertainty_pct"),
            "gear_uncertainty_pct": settings.get("gear_uncertainty_pct"),
            "min_abs_band_hz": settings.get("min_abs_band_hz"),
            "max_band_half_width_pct": settings.get("max_band_half_width_pct"),
            "tire_deflection_factor": settings.get("tire_deflection_factor"),
        }
    )
    metadata["tire_circumference_m"] = tire_circumference_m_from_spec(
        settings.get("tire_width_mm"),
        settings.get("tire_aspect_pct"),
        settings.get("rim_in"),
        deflection_factor=settings.get("tire_deflection_factor"),
    )
    if language_provider is not None:
        metadata["language"] = str(language_provider()).strip().lower() or "en"
    return metadata
