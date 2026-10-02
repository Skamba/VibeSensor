"""Production-shaped speed views for tests that drive a real ``GPSSpeedMonitor``."""

from __future__ import annotations

from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.obd.service import ObdService
from vibesensor.speed.source_coordinator import (
    SpeedSourceObservationService,
    build_speed_source_services,
)

__all__ = ["observed_speed"]


def observed_speed(gps_monitor: GPSSpeedMonitor) -> SpeedSourceObservationService:
    """Return the selected-source speed view over *gps_monitor* (OBD idle), as wired in prod."""
    return build_speed_source_services(gps_monitor=gps_monitor, obd=ObdService()).observation
