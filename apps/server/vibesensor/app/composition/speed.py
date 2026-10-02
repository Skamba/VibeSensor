from __future__ import annotations

from dataclasses import dataclass

from vibesensor.app.config_schema import AppConfig
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.obd.service import ObdService
from vibesensor.speed.source_coordinator import (
    SpeedSourceServices,
    build_speed_source_services,
)


@dataclass(frozen=True, slots=True)
class SpeedRuntimeBundle:
    """GPS, OBD, and selected-speed-source runtime services."""

    gps_monitor: GPSSpeedMonitor
    obd: ObdService
    speed_services: SpeedSourceServices


def build_speed_runtime(config: AppConfig) -> SpeedRuntimeBundle:
    """Build the grouped GPS/OBD speed-source runtime services."""

    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    obd = ObdService()
    return SpeedRuntimeBundle(
        gps_monitor=gps_monitor,
        obd=obd,
        speed_services=build_speed_source_services(gps_monitor=gps_monitor, obd=obd),
    )
