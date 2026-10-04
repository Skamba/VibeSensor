"""Stateless rotational-speed payload builders."""

from __future__ import annotations

from vibesensor.common.type_checks import NUMERIC_TYPES
from vibesensor.common.units import SECONDS_PER_MINUTE
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.speed_source import SpeedSource
from vibesensor.dsp.order_bands import build_order_bands, vehicle_orders_hz
from vibesensor.live.payload_types import (
    RotationalSpeedsPayload,
    RotationalSpeedValuePayload,
)
from vibesensor.speed.speed_source_config import ResolvedSpeedSource


def rotational_basis_speed_source(
    selected_source: str,
    *,
    gps_enabled: bool,
    resolution_source: ResolvedSpeedSource,
) -> str:
    """Determine the basis speed source label for rotational RPM display."""
    return SpeedSource.resolve_basis_label(
        str(selected_source or "gps"),
        gps_enabled=gps_enabled,
        resolution_source=resolution_source,
    )


def build_rotational_speeds_payload(
    *,
    basis_speed_source: str,
    speed_mps: float | None,
    measured_engine_rpm: float | None = None,
    analysis_settings: AnalysisSettingsSnapshot,
) -> RotationalSpeedsPayload:
    """Assemble the ``rotational_speeds`` sub-dict for the WS payload.

    Each family is independent: a missing reference blanks only its own
    family, and a fresh measured engine RPM (OBD-II) drives the engine values.
    """
    measured_rpm = (
        float(measured_engine_rpm)
        if isinstance(measured_engine_rpm, NUMERIC_TYPES)
        and not isinstance(measured_engine_rpm, bool)
        and measured_engine_rpm > 0
        else None
    )
    orders_hz = vehicle_orders_hz(
        speed_mps=speed_mps,
        settings=analysis_settings,
        measured_engine_rpm=measured_rpm,
    )
    missing_reason = (
        "speed_unavailable" if speed_mps is None or speed_mps <= 0 else "missing_reference"
    )

    def _value(hz: float | None, *, mode: str) -> RotationalSpeedValuePayload:
        if hz is None:
            return {"rpm": None, "mode": "calculated", "reason": missing_reason}
        return {"rpm": hz * SECONDS_PER_MINUTE, "mode": mode, "reason": None}

    bands = build_order_bands(orders_hz)
    return {
        "basis_speed_source": basis_speed_source,
        "wheel": _value(orders_hz.get("wheel_hz"), mode="calculated"),
        "driveshaft": _value(orders_hz.get("drive_hz"), mode="calculated"),
        "engine": _value(
            orders_hz.get("engine_hz"),
            mode="measured" if measured_rpm is not None else "calculated",
        ),
        "order_bands": bands or None,
    }
