"""Stateless rotational-speed payload builders."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from vibesensor.domain.speed_source import SpeedSource
from vibesensor.shared.constants import SECONDS_PER_MINUTE
from vibesensor.shared.types.payload_types import (
    RotationalSpeedsPayload,
    RotationalSpeedValuePayload,
)
from vibesensor.use_cases.diagnostics import build_order_bands, vehicle_orders_hz

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.infra.config.settings_store import SettingsStore


def rotational_basis_speed_source(
    settings_store: SettingsStore,
    gps_monitor: GPSSpeedMonitor,
    *,
    resolution_source: str | None = None,
) -> str:
    """Determine the basis speed source label for rotational RPM display."""
    speed_source = settings_store.get_speed_source()
    selected_source = str(speed_source.get("speedSource") or "gps")
    return SpeedSource.resolve_basis_label(
        selected_source,
        gps_enabled=gps_monitor.gps_enabled,
        fallback_active=gps_monitor.fallback_active,
        resolution_source=resolution_source,
    )


def build_rotational_speeds_payload(
    *,
    basis_speed_source: str,
    speed_mps: float | None,
    analysis_settings: Mapping[str, object],
) -> RotationalSpeedsPayload:
    """Assemble the ``rotational_speeds`` sub-dict for the WS payload."""
    if speed_mps is None or speed_mps <= 0:
        reason: str | None = "speed_unavailable"
        orders_hz = None
    else:
        orders_hz = vehicle_orders_hz(speed_mps=speed_mps, settings=analysis_settings)
        reason = "invalid_vehicle_settings" if orders_hz is None else None

    if reason is not None:
        _component: RotationalSpeedValuePayload = {
            "rpm": None,
            "mode": "calculated",
            "reason": reason,
        }
        return {
            "basis_speed_source": basis_speed_source,
            "wheel": {**_component},
            "driveshaft": {**_component},
            "engine": {**_component},
            "order_bands": None,
        }

    assert orders_hz is not None
    wheel_rpm = float(orders_hz["wheel_hz"]) * SECONDS_PER_MINUTE
    drive_rpm = float(orders_hz["drive_hz"]) * SECONDS_PER_MINUTE
    engine_rpm = float(orders_hz["engine_hz"]) * SECONDS_PER_MINUTE

    return {
        "basis_speed_source": basis_speed_source,
        "wheel": {"rpm": wheel_rpm, "mode": "calculated", "reason": None},
        "driveshaft": {"rpm": drive_rpm, "mode": "calculated", "reason": None},
        "engine": {"rpm": engine_rpm, "mode": "calculated", "reason": None},
        "order_bands": build_order_bands(orders_hz, analysis_settings),
    }
