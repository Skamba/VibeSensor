"""Order-band math and diagnostic settings.

Computes vehicle-order frequencies (wheel, driveshaft, engine) and tolerance
bands from speed and car-specification analysis settings.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite, sqrt

from .analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_mps,
)
from .constants import (
    FREQUENCY_EPSILON_HZ,
    HARMONIC_2X,
    MIN_OVERLAP_TOLERANCE,
)
from .domain_models import as_float_or_none
from .payload_types import OrderBandPayload

DEFAULT_DIAGNOSTIC_SETTINGS = DEFAULT_ANALYSIS_SETTINGS


def build_diagnostic_settings(overrides: Mapping[str, object] | None = None) -> dict[str, float]:
    """Return analysis settings merged with validated *overrides*."""
    out = dict(DEFAULT_ANALYSIS_SETTINGS)
    if not overrides:
        return out
    for key in DEFAULT_ANALYSIS_SETTINGS:
        parsed = as_float_or_none(overrides.get(key))
        if parsed is not None:
            out[key] = parsed
    return out


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
    settings: dict[str, float],
) -> tuple[float, float, float]:
    """Compute (wheel_tol, drive_tol, engine_tol) for the given order frequencies.

    Both callers (build_order_bands and classify_peak_hz) need
    the same trio of tolerance values.  Centralising the computation here avoids
    repeating the five-parameter call pattern three times per site.
    """
    common = {
        "min_abs_band_hz": settings["min_abs_band_hz"],
        "max_band_half_width_pct": settings["max_band_half_width_pct"],
    }
    wheel_tol = tolerance_for_order(
        settings["wheel_bandwidth_pct"],
        orders_hz["wheel_hz"],
        orders_hz["wheel_uncertainty_pct"],
        **common,
    )
    drive_tol = tolerance_for_order(
        settings["driveshaft_bandwidth_pct"],
        orders_hz["drive_hz"],
        orders_hz["drive_uncertainty_pct"],
        **common,
    )
    engine_tol = tolerance_for_order(
        settings["engine_bandwidth_pct"],
        orders_hz["engine_hz"],
        orders_hz["engine_uncertainty_pct"],
        **common,
    )
    return wheel_tol, drive_tol, engine_tol


def build_order_bands(
    orders_hz: dict[str, float],
    analysis_settings: Mapping[str, object],
) -> list[OrderBandPayload]:
    """Pre-compute order tolerance bands so the frontend doesn't duplicate this math.

    This is a pure function that depends only on the order frequencies and
    analysis settings — no runtime state required.
    """
    resolved = build_diagnostic_settings(analysis_settings)
    wheel_hz = float(orders_hz["wheel_hz"])
    drive_hz = float(orders_hz["drive_hz"])
    engine_hz = float(orders_hz["engine_hz"])
    wheel_tol, drive_tol, engine_tol = order_tolerances(orders_hz, resolved)
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
    settings: Mapping[str, object],
) -> dict[str, float] | None:
    """Return per-order frequencies in Hz for the given speed and settings.

    Returns ``None`` when *speed_mps* is unavailable or non-positive.
    """
    if speed_mps is None or not isfinite(speed_mps) or speed_mps <= 0:
        return None
    # build_diagnostic_settings guarantees all DEFAULT_ANALYSIS_SETTINGS keys
    # are present as finite floats, so as_float_or_none / isfinite guards are
    # unnecessary for those keys.
    spec_settings = build_diagnostic_settings(settings)
    circumference = tire_circumference_m_from_spec(
        spec_settings["tire_width_mm"],
        spec_settings["tire_aspect_pct"],
        spec_settings["rim_in"],
        deflection_factor=spec_settings["tire_deflection_factor"],
    )
    if circumference is None or circumference <= 0:
        return None
    final_drive_ratio = spec_settings["final_drive_ratio"]
    gear_ratio = spec_settings["current_gear_ratio"]
    if final_drive_ratio <= 0 or gear_ratio <= 0:
        return None

    whz = wheel_hz_from_speed_mps(speed_mps, circumference)
    if whz is None:
        return None
    wheel_hz = whz
    drive_hz = wheel_hz * final_drive_ratio
    engine_hz = drive_hz * gear_ratio
    if not all(isfinite(v) and v > 0 for v in (wheel_hz, drive_hz, engine_hz)):
        return None
    speed_uncertainty_pct = max(0.0, spec_settings["speed_uncertainty_pct"]) / 100.0
    tire_uncertainty_pct = max(0.0, spec_settings["tire_diameter_uncertainty_pct"]) / 100.0
    final_drive_uncertainty_pct = max(0.0, spec_settings["final_drive_uncertainty_pct"]) / 100.0
    gear_uncertainty_pct = max(0.0, spec_settings["gear_uncertainty_pct"]) / 100.0
    wheel_uncertainty_pct = combined_relative_uncertainty(
        speed_uncertainty_pct,
        tire_uncertainty_pct,
    )
    drive_uncertainty_pct = combined_relative_uncertainty(
        wheel_uncertainty_pct,
        final_drive_uncertainty_pct,
    )
    engine_uncertainty_pct = combined_relative_uncertainty(
        drive_uncertainty_pct,
        gear_uncertainty_pct,
    )
    return {
        "wheel_hz": wheel_hz,
        "drive_hz": drive_hz,
        "engine_hz": engine_hz,
        "wheel_uncertainty_pct": wheel_uncertainty_pct,
        "drive_uncertainty_pct": drive_uncertainty_pct,
        "engine_uncertainty_pct": engine_uncertainty_pct,
    }
