from __future__ import annotations

import asyncio
import csv
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from .gps_speed import GPSSpeedMonitor
from .registry import ClientRegistry

CSV_COLUMNS = [
    "timestamp_iso",
    "client_id",
    "axis",
    "rms",
    "p2p",
    "peak1_hz",
    "peak1_amp",
    "peak2_hz",
    "peak2_amp",
    "peak3_hz",
    "peak3_amp",
    "frames_dropped_total",
    "queue_overflow_drops",
    "speed_mps",
]


class MetricsLogger:
    def __init__(
        self,
        enabled: bool,
        csv_path: Path,
        metrics_log_hz: int,
        registry: ClientRegistry,
        gps_monitor: GPSSpeedMonitor,
    ):
        self.enabled = bool(enabled)
        self.csv_path = csv_path
        self.metrics_log_hz = max(1, metrics_log_hz)
        self.registry = registry
        self.gps_monitor = gps_monitor
        self._lock = RLock()
        self._active_path: Path | None = None
        if self.enabled:
            self._active_path = self._path_for_new_session()

    def _path_for_new_session(self, now: datetime | None = None) -> Path:
        ts = now or datetime.now(UTC)
        date_suffix = ts.strftime("%Y%m%d_%H%M%S")
        stem = self.csv_path.stem
        return self.csv_path.with_name(f"{stem}_{date_suffix}{self.csv_path.suffix or '.csv'}")

    def status(self) -> dict[str, str | bool | None]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "current_file": self._active_path.name if self._active_path else None,
            }

    def start_logging(self) -> dict[str, str | bool | None]:
        with self._lock:
            self.enabled = True
            self._active_path = self._path_for_new_session()
            return self.status()

    def stop_logging(self) -> dict[str, str | bool | None]:
        with self._lock:
            self.enabled = False
            self._active_path = None
            return self.status()

    def _append_rows(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        needs_header = not path.exists()
        ts = datetime.now(UTC).isoformat()
        speed_mps = self.gps_monitor.speed_mps

        rows: list[list[object]] = []
        for record in self.registry.iter_records():
            metrics = record.latest_metrics
            if not metrics:
                continue
            for axis in ("x", "y", "z"):
                axis_metrics = metrics.get(axis)
                if not isinstance(axis_metrics, dict):
                    continue
                peaks = axis_metrics.get("peaks", [])
                peak_vals = []
                for idx in range(3):
                    if idx < len(peaks):
                        peak_vals.extend([peaks[idx].get("hz", 0.0), peaks[idx].get("amp", 0.0)])
                    else:
                        peak_vals.extend([0.0, 0.0])
                rows.append(
                    [
                        ts,
                        record.client_id,
                        axis,
                        axis_metrics.get("rms", 0.0),
                        axis_metrics.get("p2p", 0.0),
                        *peak_vals,
                        record.frames_dropped,
                        record.queue_overflow_drops,
                        speed_mps if speed_mps is not None else "",
                    ]
                )

        if not rows:
            return

        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if needs_header:
                writer.writerow(CSV_COLUMNS)
            writer.writerows(rows)

    async def run(self) -> None:
        interval = 1.0 / self.metrics_log_hz
        while True:
            with self._lock:
                active = self.enabled
                path = self._active_path
            if active and path is not None:
                await asyncio.to_thread(self._append_rows, path)
            await asyncio.sleep(interval)
