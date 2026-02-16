from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .analysis_settings import AnalysisSettingsStore, tire_circumference_m_from_spec
from .gps_speed import GPSSpeedMonitor
from .processing import SignalProcessor
from .registry import ClientRegistry
from .runlog import (
    append_jsonl_records,
    create_run_end_record,
    create_run_metadata,
    utc_now_iso,
)


class MetricsLogger:
    def __init__(
        self,
        enabled: bool,
        log_path: Path,
        metrics_log_hz: int,
        registry: ClientRegistry,
        gps_monitor: GPSSpeedMonitor,
        processor: SignalProcessor,
        analysis_settings: AnalysisSettingsStore,
        sensor_model: str,
        default_sample_rate_hz: int,
        fft_window_size_samples: int,
        fft_window_type: str = "hann",
        peak_picker_method: str = "max_peak_amp_across_axes",
        accel_scale_g_per_lsb: float | None = None,
    ):
        self.enabled = bool(enabled)
        self.log_path = log_path
        self.metrics_log_hz = max(1, metrics_log_hz)
        self.registry = registry
        self.gps_monitor = gps_monitor
        self.processor = processor
        self.analysis_settings = analysis_settings
        self.sensor_model = sensor_model.strip() or "unknown"
        self.default_sample_rate_hz = int(default_sample_rate_hz)
        self.fft_window_size_samples = int(fft_window_size_samples)
        self.fft_window_type = fft_window_type
        self.peak_picker_method = peak_picker_method
        self.accel_scale_g_per_lsb = (
            float(accel_scale_g_per_lsb)
            if isinstance(accel_scale_g_per_lsb, (int, float)) and accel_scale_g_per_lsb > 0
            else None
        )
        self._lock = RLock()
        self._active_path: Path | None = None
        self._run_id: str | None = None
        self._run_start_utc: str | None = None
        self._run_start_mono_s: float | None = None
        self._metadata_written = False
        self._live_start_utc = utc_now_iso()
        self._live_start_mono_s = time.monotonic()
        self._live_samples: deque[dict[str, object]] = deque(maxlen=20_000)
        if self.enabled:
            self._start_new_session_locked()

    def _path_for_new_session(self, now: datetime | None = None) -> Path:
        ts = now or datetime.now(UTC)
        date_suffix = ts.strftime("%Y%m%d_%H%M%S")
        stem = self.log_path.stem
        return self.log_path.with_name(f"{stem}_{date_suffix}.jsonl")

    def _start_new_session_locked(self, now: datetime | None = None) -> None:
        self._active_path = self._path_for_new_session(now=now)
        self._run_id = uuid4().hex
        self._run_start_utc = utc_now_iso()
        self._run_start_mono_s = time.monotonic()
        self._metadata_written = False

    def _session_snapshot(self) -> tuple[Path, str, str, float] | None:
        with self._lock:
            if (
                not self.enabled
                or self._active_path is None
                or not self._run_id
                or not self._run_start_utc
                or self._run_start_mono_s is None
            ):
                return None
            return (
                self._active_path,
                self._run_id,
                self._run_start_utc,
                self._run_start_mono_s,
            )

    def status(self) -> dict[str, str | bool | None]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "current_file": self._active_path.name if self._active_path else None,
                "run_id": self._run_id,
            }

    def start_logging(self) -> dict[str, str | bool | None]:
        with self._lock:
            if self.enabled and self._active_path and self._run_id:
                self._finalize_run_locked()
            self.enabled = True
            self._start_new_session_locked()
            return self.status()

    def stop_logging(self) -> dict[str, str | bool | None]:
        with self._lock:
            if self.enabled and self._active_path and self._run_id:
                self._finalize_run_locked()
            self.enabled = False
            self._active_path = None
            self._run_id = None
            self._run_start_utc = None
            self._run_start_mono_s = None
            self._metadata_written = False
            return self.status()

    def analysis_snapshot(
        self,
        max_rows: int = 4000,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        with self._lock:
            run_id = self._run_id or "live"
            start_time_utc = self._run_start_utc or self._live_start_utc
            metadata = self._run_metadata_record(run_id=run_id, start_time_utc=start_time_utc)
            metadata["end_time_utc"] = utc_now_iso()
            samples = list(self._live_samples)
            if max_rows > 0 and len(samples) > max_rows:
                samples = samples[-max_rows:]
            return metadata, samples

    def _run_metadata_record(self, run_id: str, start_time_utc: str) -> dict[str, object]:
        settings = self.analysis_settings.snapshot()
        feature_interval_s = 1.0 / max(1.0, float(self.metrics_log_hz))
        raw_sample_rate_hz = (
            self.default_sample_rate_hz if self.default_sample_rate_hz > 0 else None
        )
        incomplete = raw_sample_rate_hz is None
        metadata = create_run_metadata(
            run_id=run_id,
            start_time_utc=start_time_utc,
            sensor_model=self.sensor_model,
            raw_sample_rate_hz=raw_sample_rate_hz,
            feature_interval_s=feature_interval_s,
            fft_window_size_samples=self.fft_window_size_samples
            if self.fft_window_size_samples > 0
            else None,
            fft_window_type=self.fft_window_type or None,
            peak_picker_method=self.peak_picker_method,
            accel_scale_g_per_lsb=self.accel_scale_g_per_lsb,
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
            }
        )
        metadata["tire_circumference_m"] = tire_circumference_m_from_spec(
            settings.get("tire_width_mm"),
            settings.get("tire_aspect_pct"),
            settings.get("rim_in"),
        )
        return metadata

    def _ensure_metadata_written(self, path: Path, run_id: str, start_time_utc: str) -> None:
        if self._metadata_written and path.exists():
            return
        append_jsonl_records(path, [self._run_metadata_record(run_id, start_time_utc)])
        self._metadata_written = True

    @staticmethod
    def _safe_metric(metrics: dict[str, object], axis: str, key: str) -> float | None:
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

    @staticmethod
    def _dominant_peak(metrics: dict[str, object]) -> tuple[float | None, float | None, str | None]:
        combined_metrics = metrics.get("combined")
        if isinstance(combined_metrics, dict):
            combined_peaks = combined_metrics.get("peaks")
            if isinstance(combined_peaks, list):
                for peak in combined_peaks:
                    if not isinstance(peak, dict):
                        continue
                    try:
                        hz = float(peak.get("hz"))
                        amp = float(peak.get("amp"))
                    except (TypeError, ValueError):
                        continue
                    if math.isnan(hz) or math.isnan(amp) or math.isinf(hz) or math.isinf(amp):
                        continue
                    if hz > 0 and amp >= 0:
                        return hz, amp, "combined"

        best_hz: float | None = None
        best_amp: float | None = None
        best_axis: str | None = None
        for axis in ("x", "y", "z"):
            axis_metrics = metrics.get(axis)
            if not isinstance(axis_metrics, dict):
                continue
            peaks = axis_metrics.get("peaks")
            if not isinstance(peaks, list) or not peaks:
                continue
            for peak in peaks:
                if not isinstance(peak, dict):
                    continue
                try:
                    hz = float(peak.get("hz"))
                    amp = float(peak.get("amp"))
                except (TypeError, ValueError):
                    continue
                if math.isnan(hz) or math.isnan(amp) or math.isinf(hz) or math.isinf(amp):
                    continue
                if best_amp is None or amp > best_amp:
                    best_amp = amp
                    best_hz = hz
                    best_axis = axis
        return best_hz, best_amp, best_axis

    def _build_sample_records(
        self, *, run_id: str, t_s: float, timestamp_utc: str
    ) -> list[dict[str, object]]:
        settings = self.analysis_settings.snapshot()
        tire_circumference_m = tire_circumference_m_from_spec(
            settings.get("tire_width_mm"),
            settings.get("tire_aspect_pct"),
            settings.get("rim_in"),
        )
        final_drive_ratio = settings.get("final_drive_ratio")
        gear_ratio = settings.get("current_gear_ratio")
        gps_speed_mps = self.gps_monitor.speed_mps
        effective_speed_mps = self.gps_monitor.effective_speed_mps
        gps_speed_kmh = (
            (float(gps_speed_mps) * 3.6) if isinstance(gps_speed_mps, (int, float)) else None
        )
        speed_kmh = (
            (float(effective_speed_mps) * 3.6)
            if isinstance(effective_speed_mps, (int, float))
            else None
        )
        speed_source = (
            "gps"
            if gps_speed_kmh is not None
            else ("override" if speed_kmh is not None else "missing")
        )
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
            wheel_hz = (speed_kmh / 3.6) / tire_circumference_m
            engine_rpm_estimated = wheel_hz * final_drive_ratio * gear_ratio * 60.0

        records: list[dict[str, object]] = []
        active_client_ids = sorted(set(self.registry.active_client_ids()))
        for client_id in active_client_ids:
            record = self.registry.get(client_id)
            if record is None:
                continue
            metrics = record.latest_metrics
            if not metrics:
                continue

            latest_xyz = self.processor.latest_sample_xyz(record.client_id)
            accel_x_g = latest_xyz[0] if latest_xyz else None
            accel_y_g = latest_xyz[1] if latest_xyz else None
            accel_z_g = latest_xyz[2] if latest_xyz else None

            rms_vals = [
                val
                for val in (
                    self._safe_metric(metrics, "x", "rms"),
                    self._safe_metric(metrics, "y", "rms"),
                    self._safe_metric(metrics, "z", "rms"),
                )
                if isinstance(val, float)
            ]
            p2p_vals = [
                val
                for val in (
                    self._safe_metric(metrics, "x", "p2p"),
                    self._safe_metric(metrics, "y", "p2p"),
                    self._safe_metric(metrics, "z", "p2p"),
                )
                if isinstance(val, float)
            ]
            vib_mag_rms = self._safe_metric(metrics, "combined", "vib_mag_rms")
            vib_mag_p2p = self._safe_metric(metrics, "combined", "vib_mag_p2p")
            accel_magnitude_rms_g = (
                vib_mag_rms
                if isinstance(vib_mag_rms, float)
                else (
                    math.sqrt(sum(v * v for v in rms_vals) / max(1.0, float(len(rms_vals))))
                    if rms_vals
                    else None
                )
            )
            accel_magnitude_p2p_g = (
                vib_mag_p2p
                if isinstance(vib_mag_p2p, float)
                else (max(p2p_vals) if p2p_vals else None)
            )
            strength_metrics: dict[str, object] = {}
            root_strength_metrics = metrics.get("strength_metrics")
            if isinstance(root_strength_metrics, dict):
                strength_metrics = root_strength_metrics
            elif isinstance(metrics.get("combined"), dict):
                nested_strength_metrics = metrics.get("combined", {}).get("strength_metrics")
                if isinstance(nested_strength_metrics, dict):
                    strength_metrics = nested_strength_metrics
            top_peaks_raw = strength_metrics.get("top_strength_peaks")
            dominant_hz = None
            dominant_axis = "combined"
            if isinstance(top_peaks_raw, list) and top_peaks_raw:
                first_peak = top_peaks_raw[0]
                if isinstance(first_peak, dict):
                    dominant_hz = self._safe_metric({"combined": first_peak}, "combined", "hz")
            dominant_amp = self._safe_metric(
                {"combined": strength_metrics},
                "combined",
                "strength_peak_band_rms_amp_g",
            )
            noise_floor_amp_p20_g = self._safe_metric(
                {"combined": strength_metrics}, "combined", "noise_floor_amp_p20_g"
            )
            strength_floor_amp_g = self._safe_metric(
                {"combined": strength_metrics}, "combined", "strength_floor_amp_g"
            )
            strength_db = self._safe_metric({"combined": strength_metrics}, "combined", "strength_db")
            strength_bucket = (
                str(strength_metrics.get("strength_bucket"))
                if strength_metrics.get("strength_bucket") not in (None, "")
                else None
            )
            top_peaks: list[dict[str, float]] = []
            if isinstance(top_peaks_raw, list):
                for peak in top_peaks_raw[:5]:
                    if not isinstance(peak, dict):
                        continue
                    try:
                        hz = float(peak.get("hz"))
                        amp = float(peak.get("strength_peak_band_rms_amp_g") or peak.get("amp"))
                    except (TypeError, ValueError):
                        continue
                    if (
                        not math.isnan(hz)
                        and not math.isnan(amp)
                        and not math.isinf(hz)
                        and not math.isinf(amp)
                        and hz > 0
                    ):
                        top_peaks.append({"hz": hz, "amp": amp})

            sample_rate_hz = (
                self.processor.latest_sample_rate_hz(record.client_id)
                or int(record.sample_rate_hz or 0)
                or self.default_sample_rate_hz
                or None
            )
            records.append(
                {
                    "record_type": "sample",
                    "schema_version": "v2-jsonl",
                    "run_id": run_id,
                    "timestamp_utc": timestamp_utc,
                    "t_s": t_s,
                    "client_id": client_id,
                    "client_name": record.name,
                    "sample_rate_hz": int(sample_rate_hz) if sample_rate_hz else None,
                    "speed_kmh": speed_kmh,
                    "gps_speed_kmh": gps_speed_kmh,
                    "speed_source": speed_source,
                    "engine_rpm": engine_rpm_estimated,
                    "engine_rpm_source": (
                        "estimated_from_speed_and_ratios"
                        if engine_rpm_estimated is not None
                        else "missing"
                    ),
                    "gear": gear_ratio if isinstance(gear_ratio, float) else None,
                    "final_drive_ratio": final_drive_ratio
                    if isinstance(final_drive_ratio, float)
                    else None,
                    "accel_x_g": accel_x_g,
                    "accel_y_g": accel_y_g,
                    "accel_z_g": accel_z_g,
                    "accel_magnitude_rms_g": accel_magnitude_rms_g,
                    "accel_magnitude_p2p_g": accel_magnitude_p2p_g,
                    "vib_mag_rms_g": accel_magnitude_rms_g,
                    "vib_mag_p2p_g": accel_magnitude_p2p_g,
                    "dominant_freq_hz": dominant_hz,
                    "dominant_peak_amp_g": dominant_amp,
                    "dominant_axis": dominant_axis,
                    "top_peaks": top_peaks,
                    "noise_floor_amp_p20_g": noise_floor_amp_p20_g,
                    "strength_floor_amp_g": strength_floor_amp_g,
                    "strength_peak_band_rms_amp_g": dominant_amp,
                    "strength_db": strength_db,
                    "strength_bucket": strength_bucket,
                    "noise_floor_amp": noise_floor_amp_p20_g,
                    "frames_dropped_total": int(record.frames_dropped),
                    "queue_overflow_drops": int(record.queue_overflow_drops),
                }
            )

        return records

    def _append_records(
        self, path: Path, run_id: str, start_time_utc: str, run_start_mono_s: float
    ) -> None:
        self._ensure_metadata_written(path, run_id, start_time_utc)
        now_mono_s = time.monotonic()
        t_s = max(0.0, now_mono_s - run_start_mono_s)
        timestamp_utc = utc_now_iso()
        rows = self._build_sample_records(run_id=run_id, t_s=t_s, timestamp_utc=timestamp_utc)
        if rows:
            append_jsonl_records(path, rows)

    def _finalize_run_locked(self) -> None:
        if self._active_path is None or not self._run_id:
            return
        self._ensure_metadata_written(
            self._active_path, self._run_id, self._run_start_utc or utc_now_iso()
        )
        append_jsonl_records(
            self._active_path,
            [create_run_end_record(run_id=self._run_id, end_time_utc=utc_now_iso())],
        )

    async def run(self) -> None:
        interval = 1.0 / self.metrics_log_hz
        while True:
            timestamp_utc = utc_now_iso()
            live_t_s = max(0.0, time.monotonic() - self._live_start_mono_s)
            live_rows = self._build_sample_records(
                run_id=self._run_id or "live",
                t_s=live_t_s,
                timestamp_utc=timestamp_utc,
            )
            if live_rows:
                with self._lock:
                    self._live_samples.extend(live_rows)
            snapshot = self._session_snapshot()
            if snapshot is not None:
                path, run_id, start_time_utc, start_mono_s = snapshot
                self._append_records(path, run_id, start_time_utc, start_mono_s)
            await asyncio.sleep(interval)
