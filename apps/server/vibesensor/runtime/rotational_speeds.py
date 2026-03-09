"""Stateless rotational-speed payload builders."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..backend_types import SpeedSourcePayload
from ..constants import SECONDS_PER_MINUTE
from ..diagnostics_shared import build_order_bands, vehicle_orders_hz
from ..payload_types import (
    RotationalSpeedsPayload,
    RotationalSpeedValuePayload,
)

if TYPE_CHECKING:
    from ..gps_speed import GPSSpeedMonitor
    from ..settings_store import SettingsStore


class _SpeedSourceSettingsStore(Protocol):
    def get_speed_source(self) -> SpeedSourcePayload: ...


class _GpsMonitorState(Protocol):
    gps_enabled: bool
    fallback_active: bool


def rotational_basis_speed_source(
    settings_store: SettingsStore | _SpeedSourceSettingsStore,
    gps_monitor: GPSSpeedMonitor | _GpsMonitorState,
    *,
    resolution_source: str | None = None,
) -> str:
    """Determine the basis speed source label for rotational RPM display."""
    speed_source = settings_store.get_speed_source()
    selected_source = str(speed_source.get("speedSource") or "gps").lower()
    if selected_source == "manual":
        return "manual"
    if selected_source == "obd2":
        return "obd2"
    # Use the pre-resolved source when available for snapshot consistency.
    if resolution_source is not None:
        if resolution_source == "fallback_manual":
            return "fallback_manual"
        if gps_monitor.gps_enabled:
            return "gps"
    else:
        # Fallback for callers that don't pass a resolution.
        if gps_monitor.fallback_active:
            return "fallback_manual"
        if gps_monitor.gps_enabled:
            return "gps"
    return "unknown"


def build_rotational_speeds_payload(
    *,
    basis_speed_source: str,
    speed_mps: float | None,
    analysis_settings: dict[str, float],
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
