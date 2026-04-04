"""Shared vehicle-order math for live telemetry and diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite, sqrt

from vibesensor.domain import OrderReferenceSpec
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.boundaries.codecs import analysis_settings_snapshot_from_mapping
from vibesensor.shared.constants.analysis import (
    FREQUENCY_EPSILON_HZ,
    HARMONIC_2X,
    MIN_OVERLAP_TOLERANCE,
)
from vibesensor.shared.json_utils import as_float_or_none
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot
from vibesensor.shared.types.payload_types import OrderBandPayload

__all__ = [
    "as_float_or_none",
    "build_diagnostic_settings",
    "build_order_bands",
    "combined_relative_uncertainty",
    "order_tolerances",
    "tolerance_for_order",
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


def combined_relative_uncertainty(*parts: float) -> float:
    """Return the combined relative uncertainty as ``sqrt(sum(part²))``."""
    sum_sq = 0.0
    for part in parts:
        if part > 0:
            sum_sq += part * part
    return sqrt(sum_sq)


def tolerance_for_order(
    base_bandwidth_pct: float,
    order_hz: float,
    uncertainty_pct: float,
    *,
    min_abs_band_hz: float,
    max_band_half_width_pct: float,
) -> float:
    """Compute the half-bandwidth tolerance for an order-tracking band."""
    if order_hz <= 0:
        return 0.0
    base_half_rel = max(0.0, base_bandwidth_pct) / 200.0
    abs_floor = max(0.0, min_abs_band_hz) / max(1.0, order_hz)
    max_half_rel = max(0.005, max_band_half_width_pct / 100.0)
    combined = sqrt((base_half_rel * base_half_rel) + (uncertainty_pct * uncertainty_pct))
    return min(max_half_rel, max(combined, abs_floor))


def order_tolerances(
    orders_hz: dict[str, float],
    order_reference_spec: OrderReferenceSpec,
) -> tuple[float, float, float]:
    """Compute (wheel_tol, drive_tol, engine_tol) for the given order frequencies."""
    common = {
        "min_abs_band_hz": order_reference_spec.min_abs_band_hz,
        "max_band_half_width_pct": order_reference_spec.max_band_half_width_pct,
    }
    wheel_tol = tolerance_for_order(
        order_reference_spec.wheel_bandwidth_pct,
        orders_hz["wheel_hz"],
        orders_hz["wheel_uncertainty_pct"],
        **common,
    )
    drive_tol = tolerance_for_order(
        order_reference_spec.driveshaft_bandwidth_pct,
        orders_hz["drive_hz"],
        orders_hz["drive_uncertainty_pct"],
        **common,
    )
    engine_tol = tolerance_for_order(
        order_reference_spec.engine_bandwidth_pct,
        orders_hz["engine_hz"],
        orders_hz["engine_uncertainty_pct"],
        **common,
    )
    return wheel_tol, drive_tol, engine_tol


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
    wheel_tol, drive_tol, engine_tol = order_tolerances(orders_hz, order_reference_spec)
    bands: list[OrderBandPayload] = [
        {"key": "wheel_1x", "center_hz": wheel_hz, "tolerance": wheel_tol},
        {"key": "wheel_2x", "center_hz": wheel_hz * HARMONIC_2X, "tolerance": wheel_tol},
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
        {"key": "engine_2x", "center_hz": engine_hz * HARMONIC_2X, "tolerance": engine_tol},
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
