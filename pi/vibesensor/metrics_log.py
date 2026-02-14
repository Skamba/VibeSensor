from __future__ import annotations

import asyncio
import csv
from datetime import UTC, datetime
from pathlib import Path

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
        self.enabled = enabled
        self.csv_path = csv_path
        self.metrics_log_hz = max(1, metrics_log_hz)
        self.registry = registry
        self.gps_monitor = gps_monitor

    def _path_for_today(self) -> Path:
        date_suffix = datetime.now(UTC).strftime("%Y%m%d")
        stem = self.csv_path.stem
        return self.csv_path.with_name(f"{stem}_{date_suffix}{self.csv_path.suffix or '.csv'}")

    def _append_rows(self) -> None:
        path = self._path_for_today()
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
        if not self.enabled:
            while True:
                await asyncio.sleep(30.0)

        interval = 1.0 / self.metrics_log_hz
        while True:
            await asyncio.to_thread(self._append_rows)
            await asyncio.sleep(interval)

