"""Shared vehicle-order math for live telemetry and diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.settings.analysis_settings_codec import (
    analysis_settings_snapshot_from_mapping,
)
from vibesensor.settings.order_reference_settings import order_reference_spec_from_snapshot
from vibesensor.shared.constants.analysis import (
    FREQUENCY_EPSILON_HZ,
    HARMONIC_2X,
    MIN_OVERLAP_TOLERANCE,
    ORDER_TOLERANCE_MIN_HZ,
    ORDER_TOLERANCE_REL,
    RIGID_ORDER_PATH_COMPLIANCE,
    WHEEL_ORDER_PATH_COMPLIANCE,
)
from vibesensor.shared.json_utils import as_float_or_none
from vibesensor.shared.types.payload_types import OrderBandPayload

__all__ = [
    "as_float_or_none",
    "build_diagnostic_settings",
    "build_order_bands",
    "order_peak_tolerance_hz",
    "vehicle_orders_hz",
]


def build_diagnostic_settings(
    overrides: Mapping[str, object] | None = None,
) -> AnalysisSettingsSnapshot:
    """Return analysis settings merged with validated *overrides* as a snapshot."""
    out = dict(AnalysisSettingsSnapshot.DEFAULTS)
    if not overrides:
        return analysis_settings_snapshot_from_mapping(out)
    for key in AnalysisSettingsSnapshot.DEFAULTS:
        parsed = as_float_or_none(overrides.get(key))
        if parsed is not None:
            out[key] = parsed
    return analysis_settings_snapshot_from_mapping(out)


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


def build_order_bands(
    orders_hz: dict[str, float],
    analysis_settings: AnalysisSettingsSnapshot,
) -> list[OrderBandPayload]:
    """Pre-compute order tolerance bands so the frontend doesn't duplicate this math."""
    order_reference_spec = order_reference_spec_from_snapshot(analysis_settings)
    if order_reference_spec is None:
        return []
    wheel_hz = float(orders_hz["wheel_hz"])
    drive_hz = float(orders_hz["drive_hz"])
    engine_hz = float(orders_hz["engine_hz"])
    wheel_2x_hz = wheel_hz * HARMONIC_2X
    engine_2x_hz = engine_hz * HARMONIC_2X
    drive_tol = _relative_tolerance(drive_hz, RIGID_ORDER_PATH_COMPLIANCE)
    engine_tol = _relative_tolerance(engine_hz, RIGID_ORDER_PATH_COMPLIANCE)
    bands: list[OrderBandPayload] = [
        {
            "key": "wheel_1x",
            "center_hz": wheel_hz,
            "tolerance": _relative_tolerance(wheel_hz, WHEEL_ORDER_PATH_COMPLIANCE),
        },
        {
            "key": "wheel_2x",
            "center_hz": wheel_2x_hz,
            "tolerance": _relative_tolerance(wheel_2x_hz, WHEEL_ORDER_PATH_COMPLIANCE),
        },
    ]
    overlap_tol = max(
        MIN_OVERLAP_TOLERANCE,
        orders_hz["drive_uncertainty_pct"] + orders_hz["engine_uncertainty_pct"],
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
) -> dict[str, float] | None:
    """Return per-order frequencies in Hz for the given speed and settings."""
    if speed_mps is None or not isfinite(speed_mps) or speed_mps <= 0:
        return None
    order_reference_spec = order_reference_spec_from_snapshot(settings)
    if order_reference_spec is None:
        return None
    return order_reference_spec.orders_hz_from_speed_mps(speed_mps)
