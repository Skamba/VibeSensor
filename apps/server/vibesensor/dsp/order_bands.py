"""Shared vehicle-order math for live telemetry and diagnostics."""

from __future__ import annotations

from math import isfinite
from typing import Final

from vibesensor.common.units import SECONDS_PER_MINUTE
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.order_reference import OrderFrequencies
from vibesensor.live.payload_types import OrderBandPayload
from vibesensor.settings.order_reference_settings import order_reference_spec_from_snapshot

HARMONIC_2X: Final[float] = 2.0
"""Multiplier for the second harmonic of a fundamental frequency."""

MIN_OVERLAP_TOLERANCE: Final[float] = 0.025
"""Minimum relative tolerance used when checking whether two rotational
orders (e.g. driveshaft 1× and engine 1×) overlap in frequency."""

FREQUENCY_EPSILON_HZ: Final[float] = 1e-6
"""Tiny guard value to prevent division-by-zero in frequency ratios."""

ORDER_TOLERANCE_REL: Final[float] = 0.08
"""Relative frequency tolerance for matching observed peaks to predicted
rotational-order frequencies."""

ORDER_TOLERANCE_MIN_HZ: Final[float] = 0.5
"""Minimum absolute frequency tolerance (Hz) for order matching, preventing
overly tight matches at low frequencies."""

WHEEL_ORDER_PATH_COMPLIANCE: Final[float] = 1.5
"""Path compliance for wheel orders: tire, hub and suspension bushings broaden
the peak, so wheel-order tolerance is widened by ``sqrt(1.5)``."""

RIGID_ORDER_PATH_COMPLIANCE: Final[float] = 1.0
"""Path compliance for stiffly coupled driveshaft and engine orders."""

__all__ = [
    "build_order_bands",
    "order_peak_tolerance_hz",
    "vehicle_orders_hz",
]


def order_peak_tolerance_hz(*, predicted_hz: float, path_compliance: float) -> float:
    """Return the match tolerance (Hz) for one predicted order frequency.

    Post-run diagnostics match peaks with this window, and live order bands
    are drawn with it too, so what the live spectrum shows as "inside the band"
    is what the report counts as an order match.
    """

    compliance_scale = path_compliance**0.5
    return float(
        max(
            ORDER_TOLERANCE_MIN_HZ,
            predicted_hz * ORDER_TOLERANCE_REL * compliance_scale,
        )
    )


def _relative_tolerance(center_hz: float, path_compliance: float) -> float:
    if center_hz <= 0:
        return 0.0
    return (
        order_peak_tolerance_hz(predicted_hz=center_hz, path_compliance=path_compliance) / center_hz
    )


def build_order_bands(orders_hz: OrderFrequencies) -> list[OrderBandPayload]:
    """Pre-compute order tolerance bands so the frontend doesn't duplicate this math.

    Only the order families present in *orders_hz* get bands.
    """
    bands: list[OrderBandPayload] = []
    wheel_hz = orders_hz.get("wheel_hz")
    drive_hz = orders_hz.get("drive_hz")
    engine_hz = orders_hz.get("engine_hz")
    if wheel_hz is not None:
        wheel_2x_hz = wheel_hz * HARMONIC_2X
        bands.append(
            {
                "key": "wheel_1x",
                "center_hz": wheel_hz,
                "tolerance": _relative_tolerance(wheel_hz, WHEEL_ORDER_PATH_COMPLIANCE),
            }
        )
        bands.append(
            {
                "key": "wheel_2x",
                "center_hz": wheel_2x_hz,
                "tolerance": _relative_tolerance(wheel_2x_hz, WHEEL_ORDER_PATH_COMPLIANCE),
            }
        )
    drive_tol = (
        _relative_tolerance(drive_hz, RIGID_ORDER_PATH_COMPLIANCE) if drive_hz is not None else 0.0
    )
    engine_tol = (
        _relative_tolerance(engine_hz, RIGID_ORDER_PATH_COMPLIANCE)
        if engine_hz is not None
        else 0.0
    )
    if drive_hz is not None and engine_hz is not None:
        overlap_tol = max(
            MIN_OVERLAP_TOLERANCE,
            orders_hz.get("drive_uncertainty_pct", 0.0)
            + orders_hz.get("engine_uncertainty_pct", 0.0),
        )
        if abs(drive_hz - engine_hz) / max(FREQUENCY_EPSILON_HZ, engine_hz) < overlap_tol:
            bands.append(
                {
                    "key": "driveshaft_engine_1x",
                    "center_hz": drive_hz,
                    "tolerance": max(drive_tol, engine_tol),
                },
            )
        else:
            bands.append({"key": "driveshaft_1x", "center_hz": drive_hz, "tolerance": drive_tol})
            bands.append({"key": "engine_1x", "center_hz": engine_hz, "tolerance": engine_tol})
    elif drive_hz is not None:
        bands.append({"key": "driveshaft_1x", "center_hz": drive_hz, "tolerance": drive_tol})
    elif engine_hz is not None:
        bands.append({"key": "engine_1x", "center_hz": engine_hz, "tolerance": engine_tol})
    if engine_hz is not None:
        engine_2x_hz = engine_hz * HARMONIC_2X
        bands.append(
            {
                "key": "engine_2x",
                "center_hz": engine_2x_hz,
                "tolerance": _relative_tolerance(engine_2x_hz, RIGID_ORDER_PATH_COMPLIANCE),
            },
        )
    return bands


def vehicle_orders_hz(
    *,
    speed_mps: float | None,
    settings: AnalysisSettingsSnapshot,
    measured_engine_rpm: float | None = None,
) -> OrderFrequencies:
    """Return the order frequencies (Hz) the car's references and live data support.

    Wheel and driveshaft orders follow speed and the tire/final drive. Engine
    orders come from a fresh measured RPM (OBD-II) when given, otherwise from
    speed and the ratios (which assumes top gear).
    """
    orders: OrderFrequencies = {}
    if speed_mps is not None and isfinite(speed_mps) and speed_mps > 0:
        order_reference_spec = order_reference_spec_from_snapshot(settings)
        if order_reference_spec is not None:
            orders = order_reference_spec.orders_hz_from_speed_mps(speed_mps)
    if (
        measured_engine_rpm is not None
        and isfinite(measured_engine_rpm)
        and measured_engine_rpm > 0
    ):
        orders["engine_hz"] = measured_engine_rpm / SECONDS_PER_MINUTE
        orders["engine_uncertainty_pct"] = 0.0
    return orders
