from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from itertools import islice
from pathlib import Path
from threading import RLock, Thread
from typing import TYPE_CHECKING
from uuid import uuid4

from vibesensor_shared.contracts import METRIC_FIELDS

from .analysis_settings import (
    AnalysisSettingsStore,
    engine_rpm_from_wheel_hz,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from .constants import MPS_TO_KMH
from .domain_models import SensorFrame
from .gps_speed import GPSSpeedMonitor
from .processing import SignalProcessor
from .registry import ClientRegistry
from .runlog import (
    create_run_metadata,
    utc_now_iso,
)

if TYPE_CHECKING:
    from .history_db import HistoryDB

LOGGER = logging.getLogger(__name__)
_MAX_POST_ANALYSIS_SAMPLES = 12_000
_LIVE_SAMPLE_WINDOW_S = 2.0
_MAX_HISTORY_CREATE_RETRIES = 5


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
        history_db: HistoryDB | None = None,
        persist_history_db: bool = True,
        language_provider: Callable[[], str] | None = None,
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
        self._run_id: str | None = None
        self._run_start_utc: str | None = None
        self._run_start_mono_s: float | None = None
        self._last_write_error: str | None = None
        self._history_db = history_db
        self._persist_history_db = bool(persist_history_db)
        self._language_provider = language_provider
        self._history_run_created = False
        self._history_create_fail_count = 0
        self._written_sample_count = 0
        self._no_data_timeout_s = 3.0
        self._last_data_progress_mono_s: float | None = None
        self._last_active_frames_total = 0
        self._live_start_utc = utc_now_iso()
        self._live_start_mono_s = time.monotonic()
        self._live_samples: deque[dict[str, object]] = deque(maxlen=20_000)
        self._live_sample_window_s = float(_LIVE_SAMPLE_WINDOW_S)
        self._analysis_thread: Thread | None = None
        self._analysis_queue: deque[str] = deque()
        self._analysis_enqueued_run_ids: set[str] = set()
        self._analysis_active_run_id: str | None = None
        if self.enabled:
            self._start_new_session_locked()

    def _start_new_session_locked(self) -> None:
        self._run_id = uuid4().hex
        self._run_start_utc = utc_now_iso()
        self._run_start_mono_s = time.monotonic()
        self._last_write_error = None
        self._history_run_created = False
        self._history_create_fail_count = 0
        self._written_sample_count = 0
        self._last_data_progress_mono_s = self._run_start_mono_s
        self._last_active_frames_total = self._active_frames_total()

    def _set_last_write_error(self, message: str) -> None:
        with self._lock:
            self._last_write_error = message

    def _clear_last_write_error(self) -> None:
        with self._lock:
            self._last_write_error = None

    def _active_frames_total(self) -> int:
        active_ids = self.registry.active_client_ids()
        total = 0
        for client_id in active_ids:
            record = self.registry.get(client_id)
            if record is None:
                continue
            total += int(record.frames_total)
        return total

    def _refresh_data_progress_marker(self, now_mono_s: float) -> None:
        current_total = self._active_frames_total()
        if current_total > self._last_active_frames_total:
            self._last_active_frames_total = current_total
            self._last_data_progress_mono_s = now_mono_s
            return
        if current_total < self._last_active_frames_total:
            self._last_active_frames_total = current_total
            self._last_data_progress_mono_s = now_mono_s

    def _ensure_history_run_created(self, run_id: str, start_time_utc: str) -> None:
        if self._history_db is None or self._history_run_created:
            return
        if self._history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES:
            return
        metadata = self._run_metadata_record(run_id, start_time_utc)
        try:
            self._history_db.create_run(run_id, start_time_utc, metadata)
            self._history_run_created = True
            self._history_create_fail_count = 0
            self._clear_last_write_error()
        except Exception as exc:
            self._history_create_fail_count += 1
            msg = (
                f"history create_run failed"
                f" (attempt {self._history_create_fail_count}"
                f"/{_MAX_HISTORY_CREATE_RETRIES}): {exc}"
            )
            self._set_last_write_error(msg)
            if self._history_create_fail_count >= _MAX_HISTORY_CREATE_RETRIES:
                LOGGER.error(
                    "Persistent DB failure: giving up after %d attempts for run %s — "
                    "all subsequent samples will be dropped. Error: %s",
                    self._history_create_fail_count,
                    run_id,
                    exc,
                    exc_info=True,
                )
            else:
                LOGGER.warning(
                    "Failed to create history run in DB (attempt %d)",
                    self._history_create_fail_count,
                    exc_info=True,
                )

    def _session_snapshot(self) -> tuple[str, str, float] | None:
        with self._lock:
            if (
                not self.enabled
                or not self._run_id
                or not self._run_start_utc
                or self._run_start_mono_s is None
            ):
                return None
            return (
                self._run_id,
                self._run_start_utc,
                self._run_start_mono_s,
            )

    def status(self) -> dict[str, str | bool | None]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "current_file": None,
                "run_id": self._run_id,
                "write_error": self._last_write_error,
                "analysis_in_progress": bool(
                    self._analysis_active_run_id
                    or self._analysis_queue
                    or (self._analysis_thread and self._analysis_thread.is_alive())
                ),
            }

    def start_logging(self) -> dict[str, str | bool | None]:
        completed_run_id: str | None = None
        with self._lock:
            if self.enabled and self._run_id:
                if self._history_run_created and self._written_sample_count > 0:
                    completed_run_id = self._run_id
                self._finalize_run_locked()
            self.enabled = True
            self._start_new_session_locked()
            self._live_samples.clear()
            self._live_start_utc = self._run_start_utc or utc_now_iso()
            self._live_start_mono_s = self._run_start_mono_s or time.monotonic()
            result = self.status()
        if completed_run_id and self._history_db is not None:
            self._schedule_post_analysis(completed_run_id)
        return result

    def stop_logging(self) -> dict[str, str | bool | None]:
        with self._lock:
            run_id_to_analyze: str | None = None
            if self.enabled and self._run_id:
                if self._history_run_created and self._written_sample_count > 0:
                    run_id_to_analyze = self._run_id
                self._finalize_run_locked()
            self.enabled = False
            self._run_id = None
            self._run_start_utc = None
            self._run_start_mono_s = None
            self._last_write_error = None
            self._history_run_created = False
            self._history_create_fail_count = 0
            self._written_sample_count = 0
            self._last_data_progress_mono_s = None
            self._last_active_frames_total = 0
            result = self.status()
        if run_id_to_analyze and self._history_db is not None:
            self._schedule_post_analysis(run_id_to_analyze)
        return result

    def analysis_snapshot(
        self,
        max_rows: int = 4000,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        with self._lock:
            run_id = self._run_id or "live"
            start_time_utc = self._run_start_utc or self._live_start_utc
            metadata = self._run_metadata_record(run_id=run_id, start_time_utc=start_time_utc)
            metadata["end_time_utc"] = utc_now_iso()
            if max_rows <= 0:
                samples = list(self._live_samples)
            else:
                samples = list(islice(reversed(self._live_samples), max_rows))
                samples.reverse()
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
            firmware_version=self._firmware_version_for_run(),
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
        if self._language_provider is not None:
            metadata["language"] = str(self._language_provider()).strip().lower() or "en"
        return metadata

    def _firmware_version_for_run(self) -> str | None:
        versions: set[str] = set()
        for client_id in self.registry.active_client_ids():
            record = self.registry.get(client_id)
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
        override_speed_mps = self.gps_monitor.override_speed_mps
        gps_speed_kmh = (
            (float(gps_speed_mps) * MPS_TO_KMH) if isinstance(gps_speed_mps, (int, float)) else None
        )
        speed_kmh = (
            (float(effective_speed_mps) * MPS_TO_KMH)
            if isinstance(effective_speed_mps, (int, float))
            else None
        )
        speed_source = (
            "override"
            if isinstance(override_speed_mps, (int, float))
            else ("gps" if gps_speed_kmh is not None else "missing")
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
            whz = wheel_hz_from_speed_kmh(speed_kmh, tire_circumference_m)
            if whz is not None:
                engine_rpm_estimated = engine_rpm_from_wheel_hz(whz, final_drive_ratio, gear_ratio)

        records: list[dict[str, object]] = []
        # Only include clients that received data recently to avoid
        # recording stale buffered data with fresh timestamps.
        active_client_ids = sorted(
            set(
                self.processor.clients_with_recent_data(
                    self.registry.active_client_ids(), max_age_s=_LIVE_SAMPLE_WINDOW_S
                )
            )
        )
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

            strength_metrics: dict[str, object] = {}
            root_strength_metrics = metrics.get("strength_metrics")
            if isinstance(root_strength_metrics, dict):
                strength_metrics = root_strength_metrics
            elif isinstance(metrics.get("combined"), dict):
                nested_strength_metrics = metrics.get("combined", {}).get("strength_metrics")
                if isinstance(nested_strength_metrics, dict):
                    strength_metrics = nested_strength_metrics
            top_peaks_raw = strength_metrics.get("top_peaks")
            dominant_hz = None
            dominant_axis = "combined"
            if isinstance(top_peaks_raw, list) and top_peaks_raw:
                first_peak = top_peaks_raw[0]
                if isinstance(first_peak, dict):
                    dominant_hz = self._safe_metric({"combined": first_peak}, "combined", "hz")
            vibration_strength_db = self._safe_metric(
                {"combined": strength_metrics}, "combined", METRIC_FIELDS["vibration_strength_db"]
            )
            strength_bucket = (
                str(strength_metrics.get(METRIC_FIELDS["strength_bucket"]))
                if strength_metrics.get(METRIC_FIELDS["strength_bucket"]) not in (None, "")
                else None
            )
            strength_peak_amp_g = self._safe_metric(
                {"combined": strength_metrics},
                "combined",
                "peak_amp_g",
            )
            strength_floor_amp_g = self._safe_metric(
                {"combined": strength_metrics},
                "combined",
                "noise_floor_amp_g",
            )
            top_peaks: list[dict[str, object]] = []
            if isinstance(top_peaks_raw, list):
                for peak in top_peaks_raw[:5]:
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
                        peak_db = self._safe_metric(
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

            sample_rate_hz = (
                self.processor.latest_sample_rate_hz(record.client_id)
                or int(record.sample_rate_hz or 0)
                or self.default_sample_rate_hz
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
                dominant_axis=dominant_axis,
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

    def _append_records(
        self,
        run_id: str,
        start_time_utc: str,
        run_start_mono_s: float,
        *,
        prebuilt_rows: list[dict[str, object]] | None = None,
    ) -> bool:
        now_mono_s = time.monotonic()
        self._refresh_data_progress_marker(now_mono_s)
        t_s = max(0.0, now_mono_s - run_start_mono_s)
        timestamp_utc = utc_now_iso()
        if prebuilt_rows is not None:
            # Re-stamp t_s and timestamp_utc for the recording time-base;
            # avoids a second expensive _build_sample_records() call.
            rows = [{**row, "t_s": t_s, "timestamp_utc": timestamp_utc} for row in prebuilt_rows]
        else:
            rows = self._build_sample_records(run_id=run_id, t_s=t_s, timestamp_utc=timestamp_utc)
        if rows:
            self._last_data_progress_mono_s = now_mono_s
            if self._history_db is not None and self._persist_history_db:
                self._ensure_history_run_created(run_id, start_time_utc)
                if self._history_run_created:
                    try:
                        self._history_db.append_samples(run_id, rows)
                        self._written_sample_count += len(rows)
                        self._clear_last_write_error()
                    except Exception as exc:
                        self._set_last_write_error(f"history append_samples failed: {exc}")
                        LOGGER.warning("Failed to append samples to history DB", exc_info=True)
                else:
                    LOGGER.warning(
                        "Dropping %d sample(s) for run %s: "
                        "history run not created (fail count %d/%d)",
                        len(rows),
                        run_id,
                        self._history_create_fail_count,
                        _MAX_HISTORY_CREATE_RETRIES,
                    )
            else:
                self._written_sample_count += len(rows)

        if self._last_data_progress_mono_s is None:
            return False
        return (now_mono_s - self._last_data_progress_mono_s) >= self._no_data_timeout_s

    def _prune_live_samples_locked(self, live_t_s: float) -> None:
        """Keep only the rolling live window used by the dashboard."""
        cutoff = float(live_t_s) - max(0.0, self._live_sample_window_s)
        while self._live_samples:
            oldest = self._live_samples[0]
            ts = oldest.get("t_s")
            if not isinstance(ts, (int, float)):
                # Defensive: drop malformed rows so stale entries cannot linger.
                self._live_samples.popleft()
                continue
            if float(ts) >= cutoff:
                break
            self._live_samples.popleft()

    def _finalize_run_locked(self) -> None:
        if not self._run_id:
            return
        if not self._history_run_created:
            return
        end_utc = utc_now_iso()
        if self._history_db is not None:
            try:
                self._history_db.finalize_run(self._run_id, end_utc)
                self._clear_last_write_error()
            except Exception as exc:
                self._set_last_write_error(f"history finalize_run failed: {exc}")
                LOGGER.warning("Failed to finalize run in history DB", exc_info=True)

    def _schedule_post_analysis(self, run_id: str) -> None:
        LOGGER.info("Analysis queued for run %s", run_id)
        with self._lock:
            if run_id in self._analysis_enqueued_run_ids or run_id == self._analysis_active_run_id:
                return
            self._analysis_queue.append(run_id)
            self._analysis_enqueued_run_ids.add(run_id)
            worker = self._analysis_thread
            if worker is None or not worker.is_alive():
                worker = Thread(
                    target=self._analysis_worker_loop,
                    name="metrics-post-analysis-worker",
                    daemon=True,
                )
                self._analysis_thread = worker
                worker.start()

    def _analysis_worker_loop(self) -> None:
        while True:
            with self._lock:
                if not self._analysis_queue:
                    self._analysis_active_run_id = None
                    return
                run_id = self._analysis_queue.popleft()
                self._analysis_active_run_id = run_id
            try:
                self._run_post_analysis(run_id)
            finally:
                with self._lock:
                    self._analysis_enqueued_run_ids.discard(run_id)
                    self._analysis_active_run_id = None

    def wait_for_post_analysis(self, timeout_s: float = 30.0) -> bool:
        """Block until post-analysis finishes or *timeout_s* elapses.

        Returns ``True`` when all queued analysis work completed within the
        deadline, ``False`` if the timeout was reached while work was still
        in progress.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            with self._lock:
                worker = self._analysis_thread
                queued = bool(self._analysis_queue)
                active_run = self._analysis_active_run_id is not None
                worker_alive = bool(worker and worker.is_alive())
            if not queued and not active_run and not worker_alive:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                LOGGER.warning(
                    "wait_for_post_analysis timed out after %.1fs "
                    "(queued=%s, active=%s, worker_alive=%s)",
                    timeout_s,
                    queued,
                    active_run,
                    worker_alive,
                )
                return False
            if worker is not None and worker_alive:
                worker.join(timeout=min(0.2, remaining))
            else:
                time.sleep(min(0.05, remaining))

    def _run_post_analysis(self, run_id: str) -> None:
        """Run thorough post-run analysis and store results in history DB."""
        if self._history_db is None:
            return
        analysis_start = time.monotonic()
        LOGGER.info("Analysis started for run %s", run_id)
        try:
            from .report.summary import summarize_run_data
            from .runlog import normalize_sample_record

            metadata = self._history_db.get_run_metadata(run_id)
            if metadata is None:
                LOGGER.warning("Cannot analyse run %s: metadata not found", run_id)
                return
            language = str(metadata.get("language") or "en")
            samples: list[dict[str, object]] = []
            total_sample_count = 0
            stride = 1
            for batch in self._history_db.iter_run_samples(run_id, batch_size=1024):
                for sample in batch:
                    total_sample_count += 1
                    if (total_sample_count - 1) % stride != 0:
                        continue
                    samples.append(normalize_sample_record(sample))
                    if len(samples) > _MAX_POST_ANALYSIS_SAMPLES:
                        samples = samples[::2]
                        stride *= 2
            if not samples:
                LOGGER.warning("Skipping post-analysis for run %s: no samples collected", run_id)
                self._history_db.store_analysis_error(run_id, "No samples collected during run")
                return
            summary = summarize_run_data(
                metadata, samples, lang=language, file_name=run_id, include_samples=False
            )
            summary["analysis_metadata"] = {
                "analyzed_sample_count": len(samples),
                "total_sample_count": total_sample_count,
                "sampling_method": "full" if stride == 1 else f"stride_{stride}",
            }
            if stride > 1:
                if language == "nl":
                    check = "Analysebemonstering"
                    explanation = (
                        f"Lange run geanalyseerd met stride {stride}. "
                        "Korte, intermitterende events "
                        "kunnen ondervertegenwoordigd zijn."
                    )
                else:
                    check = "Analysis sampling"
                    explanation = (
                        f"Long run analyzed with stride {stride}. Brief intermittent events may be "
                        "underrepresented."
                    )
                summary.setdefault("run_suitability", []).append(
                    {
                        "check": check,
                        "check_key": "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
                        "state": "warn",
                        "explanation": explanation,
                    }
                )
            self._history_db.store_analysis(run_id, summary)
            duration_s = time.monotonic() - analysis_start
            LOGGER.info(
                "Analysis completed for run %s: %d samples in %.2fs",
                run_id,
                len(samples),
                duration_s,
            )
        except Exception as exc:
            duration_s = time.monotonic() - analysis_start
            self._set_last_write_error(f"post-analysis failed for run {run_id}: {exc}")
            LOGGER.warning(
                "Analysis failed for run %s after %.2fs: %s",
                run_id,
                duration_s,
                exc,
                exc_info=True,
            )
            try:
                self._history_db.store_analysis_error(run_id, str(exc))
            except Exception as store_exc:
                self._set_last_write_error(
                    f"history store_analysis_error failed for run {run_id}: {store_exc}"
                )
                LOGGER.warning("Failed to store analysis error for run %s", run_id, exc_info=True)

    async def run(self) -> None:
        interval = 1.0 / self.metrics_log_hz
        while True:
            try:
                timestamp_utc = utc_now_iso()
                live_t_s = max(0.0, time.monotonic() - self._live_start_mono_s)
                live_rows = self._build_sample_records(
                    run_id=self._run_id or "live",
                    t_s=live_t_s,
                    timestamp_utc=timestamp_utc,
                )
                with self._lock:
                    if live_rows:
                        self._live_samples.extend(live_rows)
                    self._prune_live_samples_locked(live_t_s)
                snapshot = self._session_snapshot()
                if snapshot is not None:
                    run_id, start_time_utc, start_mono_s = snapshot
                    no_data_timeout = self._append_records(
                        run_id,
                        start_time_utc,
                        start_mono_s,
                        prebuilt_rows=live_rows,
                    )
                    if no_data_timeout:
                        LOGGER.info(
                            "Auto-stopping run %s after %.1fs without new data",
                            run_id,
                            self._no_data_timeout_s,
                        )
                        self.stop_logging()
            except Exception as exc:
                self._set_last_write_error(f"metrics logger tick failed: {exc}")
                LOGGER.warning(
                    "Metrics logger tick failed; will retry next interval.",
                    exc_info=True,
                )
            await asyncio.sleep(interval)
