from __future__ import annotations

import time

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor


def set_gps_snapshot_age(
    monitor: GPSSpeedMonitor,
    *,
    age_s: float | None = 0.0,
) -> None:
    """Set the GPS snapshot timestamp for tests while preserving the current speed."""
    timestamp = None if age_s is None else time.monotonic() - age_s
    monitor._speed_snapshot = (monitor.speed_mps, timestamp)
