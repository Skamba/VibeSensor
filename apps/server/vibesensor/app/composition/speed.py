from __future__ import annotations

from dataclasses import dataclass

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.obd import ObdAdminClient, ObdRuntime, build_obd_runtime
from vibesensor.adapters.speed import SpeedSourceServices, build_speed_source_services
from vibesensor.app.config_schema import AppConfig


@dataclass(frozen=True, slots=True)
class SpeedRuntimeBundle:
    """GPS, OBD, and selected-speed-source runtime services."""

    gps_monitor: GPSSpeedMonitor
    obd_runtime: ObdRuntime
    speed_services: SpeedSourceServices


def build_speed_runtime(config: AppConfig) -> SpeedRuntimeBundle:
    """Build the grouped GPS/OBD speed-source runtime services."""

    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    obd_admin_client = ObdAdminClient()
    obd_runtime = build_obd_runtime(admin_client=obd_admin_client)
    return SpeedRuntimeBundle(
        gps_monitor=gps_monitor,
        obd_runtime=obd_runtime,
        speed_services=build_speed_source_services(
            gps_monitor=gps_monitor,
            obd_facts=obd_runtime.observation.facts,
            obd_projection=obd_runtime.observation.projection,
            obd_device_admin=obd_admin_client,
            obd_status_refresher=obd_runtime.control.admin,
            obd_control=obd_runtime.control.settings,
        ),
    )
