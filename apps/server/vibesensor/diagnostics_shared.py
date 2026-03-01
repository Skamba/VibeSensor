from __future__ import annotations

from collections.abc import Mapping
from math import isfinite, sqrt
from typing import Any

from vibesensor_core.strength_bands import (
    DECAY_TICKS,
    HYSTERESIS_DB,
    PERSISTENCE_TICKS,
    band_by_key,
    band_rank,
    bucket_for_strength,
)

from .analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_mps,
)
from .constants import (
    FREQUENCY_EPSILON_HZ,
    HARMONIC_2X,
    MIN_OVERLAP_TOLERANCE,
    MULTI_SENSOR_CORROBORATION_DB,
    ROAD_RESONANCE_MAX_HZ,
    ROAD_RESONANCE_MIN_HZ,
)
from .runlog import as_float_or_none as _as_float

DEFAULT_DIAGNOSTIC_SETTINGS = DEFAULT_ANALYSIS_SETTINGS


def build_diagnostic_settings(overrides: Mapping[str, Any] | None = None) -> dict[str, float]:
    out = dict(DEFAULT_ANALYSIS_SETTINGS)
    if not overrides:
        return out
    for key in DEFAULT_ANALYSIS_SETTINGS:
        parsed = _as_float(overrides.get(key))
        if parsed is not None:
            out[key] = parsed
    return out


def combined_relative_uncertainty(*parts: float) -> float:
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

    Both callers (_build_order_bands in app.py and classify_peak_hz here) need
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


def vehicle_orders_hz(
    *,
    speed_mps: float | None,
    settings: Mapping[str, Any],
) -> dict[str, float] | None:
    if speed_mps is None or not isfinite(speed_mps) or speed_mps <= 0:
        return None
    spec_settings = build_diagnostic_settings(settings)
    circumference = tire_circumference_m_from_spec(
        _as_float(spec_settings.get("tire_width_mm")),
        _as_float(spec_settings.get("tire_aspect_pct")),
        _as_float(spec_settings.get("rim_in")),
        deflection_factor=_as_float(spec_settings.get("tire_deflection_factor")),
    )
    if circumference is None or circumference <= 0:
        return None
    final_drive_ratio = _as_float(spec_settings.get("final_drive_ratio"))
    gear_ratio = _as_float(spec_settings.get("current_gear_ratio"))
    if (
        final_drive_ratio is None
        or not isfinite(final_drive_ratio)
        or final_drive_ratio <= 0
        or gear_ratio is None
        or not isfinite(gear_ratio)
        or gear_ratio <= 0
    ):
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
        wheel_uncertainty_pct, final_drive_uncertainty_pct
    )
    engine_uncertainty_pct = combined_relative_uncertainty(
        drive_uncertainty_pct, gear_uncertainty_pct
    )
    return {
        "wheel_hz": wheel_hz,
        "drive_hz": drive_hz,
        "engine_hz": engine_hz,
        "wheel_uncertainty_pct": wheel_uncertainty_pct,
        "drive_uncertainty_pct": drive_uncertainty_pct,
        "engine_uncertainty_pct": engine_uncertainty_pct,
    }


_ORDER_LABELS: dict[str, str] = {
    "wheel1": "1x wheel order",
    "wheel2": "2x wheel order",
    "wheel2_eng1": "2x wheel / 1x engine order",
    "shaft_eng1": "1x driveshaft/engine order",
    "shaft1": "1x driveshaft order",
    "eng1": "1x engine order",
    "eng2": "2x engine order",
}


def _order_label_for_class_key(class_key: str) -> str | None:
    return _ORDER_LABELS.get(class_key)


_SUSPECTED_SOURCES: dict[str, str] = {
    "wheel1": "wheel/tire",
    "wheel2": "wheel/tire",
    "wheel2_eng1": "wheel/tire",  # default to wheel but ambiguous
    "shaft1": "driveline",
    "shaft_eng1": "driveline",
    "eng1": "engine",
    "eng2": "engine",
    "road": "body resonance",
}


def suspected_source_from_class_key(class_key: str) -> str:
    return _SUSPECTED_SOURCES.get(class_key, "unknown")


_SOURCE_KEYS: dict[str, tuple[str, ...]] = {
    "wheel2_eng1": ("wheel", "engine"),
    "shaft_eng1": ("driveshaft", "engine"),
    "eng1": ("engine",),
    "eng2": ("engine",),
    "shaft1": ("driveshaft",),
    "wheel1": ("wheel",),
    "wheel2": ("wheel",),
}


def source_keys_from_class_key(class_key: str) -> tuple[str, ...]:
    return _SOURCE_KEYS.get(class_key, ("other",))


def classify_peak_hz(
    *,
    peak_hz: float,
    speed_mps: float | None,
    settings: Mapping[str, Any],
) -> dict[str, object]:
    candidates: list[dict[str, float | str]] = []
    order_refs = vehicle_orders_hz(speed_mps=speed_mps, settings=settings)
    resolved_settings = build_diagnostic_settings(settings)
    if order_refs:
        wheel_hz = order_refs["wheel_hz"]
        drive_hz = order_refs["drive_hz"]
        engine_hz = order_refs["engine_hz"]
        wheel_tol, drive_tol, engine_tol = order_tolerances(order_refs, resolved_settings)
        candidates.extend(
            [
                {"hz": wheel_hz, "tol": wheel_tol, "key": "wheel1"},
            ]
        )
        # Detect wheel_2x / engine_1x overlap: when 2×wheel_hz ≈ engine_hz,
        # merge them into a combined class to avoid misattribution.
        wheel_2x_hz = wheel_hz * HARMONIC_2X
        wheel2_eng1_overlap_tol = max(
            MIN_OVERLAP_TOLERANCE,
            order_refs["wheel_uncertainty_pct"] + order_refs["engine_uncertainty_pct"],
        )
        rel_diff = abs(wheel_2x_hz - engine_hz) / max(FREQUENCY_EPSILON_HZ, engine_hz)
        if rel_diff < wheel2_eng1_overlap_tol:
            candidates.append(
                {
                    "hz": wheel_2x_hz,
                    "tol": max(wheel_tol, engine_tol),
                    "key": "wheel2_eng1",
                }
            )
        else:
            candidates.append({"hz": wheel_2x_hz, "tol": wheel_tol, "key": "wheel2"})

        overlap_tol = max(
            MIN_OVERLAP_TOLERANCE,
            order_refs["drive_uncertainty_pct"] + order_refs["engine_uncertainty_pct"],
        )
        if abs(drive_hz - engine_hz) / max(FREQUENCY_EPSILON_HZ, engine_hz) < overlap_tol:
            candidates.append(
                {
                    "hz": drive_hz,
                    "tol": max(drive_tol, engine_tol),
                    "key": "shaft_eng1",
                }
            )
        else:
            candidates.extend(
                [
                    {"hz": drive_hz, "tol": drive_tol, "key": "shaft1"},
                    {"hz": engine_hz, "tol": engine_tol, "key": "eng1"},
                ]
            )
        candidates.append({"hz": engine_hz * HARMONIC_2X, "tol": engine_tol, "key": "eng2"})

    best: dict[str, float | str] | None = None
    best_err = float("inf")
    for candidate in candidates:
        hz = float(candidate["hz"])
        if hz <= 0.2:
            continue
        rel_err = abs(peak_hz - hz) / hz
        tol = float(candidate["tol"])
        if rel_err <= tol and rel_err < best_err:
            best = candidate
            best_err = rel_err

    if best is not None:
        class_key = str(best["key"])
        return {
            "key": class_key,
            "matched_hz": float(best["hz"]),
            "rel_err": best_err,
            "tol": float(best["tol"]),
            "order_label": _order_label_for_class_key(class_key),
            "suspected_source": suspected_source_from_class_key(class_key),
        }
    if ROAD_RESONANCE_MIN_HZ <= peak_hz <= ROAD_RESONANCE_MAX_HZ:
        return {
            "key": "road",
            "matched_hz": None,
            "rel_err": None,
            "tol": None,
            "order_label": None,
            "suspected_source": suspected_source_from_class_key("road"),
        }
    return {
        "key": "other",
        "matched_hz": None,
        "rel_err": None,
        "tol": None,
        "order_label": None,
        "suspected_source": suspected_source_from_class_key("other"),
    }


def severity_from_peak(
    *,
    vibration_strength_db: float,
    sensor_count: int,
    prior_state: dict[str, Any] | None = None,
    peak_hz: float | None = None,
    persistence_freq_bin_hz: float | None = None,
) -> dict[str, float | str | dict[str, Any]] | None:
    state = dict(prior_state or {})
    state.setdefault("current_bucket", None)
    state.setdefault("pending_bucket", None)
    state.setdefault("consecutive_up", 0)
    state.setdefault("consecutive_down", 0)
    state.setdefault("last_confirmed_hz", None)
    corroboration = MULTI_SENSOR_CORROBORATION_DB if sensor_count >= 2 else 0.0
    adjusted_db = float(vibration_strength_db) + corroboration
    candidate_bucket_raw = bucket_for_strength(adjusted_db)
    candidate_bucket = None if candidate_bucket_raw == "l0" else candidate_bucket_raw
    current_bucket = state.get("current_bucket")
    peak_hz_value = _as_float(peak_hz)
    freq_bin_hz = _as_float(persistence_freq_bin_hz)
    freq_guard_enabled = peak_hz_value is not None and freq_bin_hz is not None and freq_bin_hz > 0

    def _advance_pending(candidate: str) -> None:
        pending = state.get("pending_bucket")
        if pending == candidate:
            if freq_guard_enabled:
                last_confirmed_hz = _as_float(state.get("last_confirmed_hz"))
                if last_confirmed_hz is not None and abs(
                    float(peak_hz_value) - last_confirmed_hz
                ) > float(freq_bin_hz):
                    state["consecutive_up"] = 1
                    state["last_confirmed_hz"] = peak_hz_value
                    return
                if last_confirmed_hz is None:
                    state["last_confirmed_hz"] = peak_hz_value
            state["consecutive_up"] = int(state.get("consecutive_up", 0)) + 1
            return

        state["pending_bucket"] = candidate
        state["consecutive_up"] = 1
        state["last_confirmed_hz"] = peak_hz_value if freq_guard_enabled else None

    if candidate_bucket is None:
        if current_bucket is not None:
            current_band = band_by_key(str(current_bucket))
            if current_band and adjusted_db < float(current_band["min_db"]) - HYSTERESIS_DB:
                state["consecutive_down"] = int(state.get("consecutive_down", 0)) + 1
                if int(state["consecutive_down"]) >= DECAY_TICKS:
                    state["current_bucket"] = None
                    state["pending_bucket"] = None
                    state["consecutive_down"] = 0
                    state["consecutive_up"] = 0
                    state["last_confirmed_hz"] = None
            else:
                state["consecutive_down"] = 0
        return {"key": state.get("current_bucket"), "db": adjusted_db, "state": state}

    if current_bucket is None:
        state["consecutive_down"] = 0
        _advance_pending(candidate_bucket)
        if int(state["consecutive_up"]) >= PERSISTENCE_TICKS:
            state["current_bucket"] = candidate_bucket
            state["pending_bucket"] = None
            state["consecutive_up"] = 0
            if freq_guard_enabled:
                state["last_confirmed_hz"] = peak_hz_value
        return {"key": state.get("current_bucket"), "db": adjusted_db, "state": state}

    current_rank = band_rank(str(current_bucket))
    candidate_rank = band_rank(str(candidate_bucket))
    if candidate_rank > current_rank:
        _advance_pending(candidate_bucket)
        if int(state["consecutive_up"]) >= PERSISTENCE_TICKS:
            state["current_bucket"] = candidate_bucket
            state["pending_bucket"] = None
            state["consecutive_up"] = 0
            if freq_guard_enabled:
                state["last_confirmed_hz"] = peak_hz_value
    elif candidate_rank < current_rank:
        current_band = band_by_key(str(current_bucket))
        if current_band and adjusted_db < float(current_band["min_db"]) - HYSTERESIS_DB:
            state["consecutive_down"] = int(state.get("consecutive_down", 0)) + 1
            if int(state["consecutive_down"]) >= DECAY_TICKS:
                state["current_bucket"] = candidate_bucket
                state["pending_bucket"] = None
                state["consecutive_down"] = 0
                state["consecutive_up"] = 0
                state["last_confirmed_hz"] = None
        else:
            state["consecutive_down"] = 0
    else:
        state["pending_bucket"] = None
        state["consecutive_up"] = 0
        state["last_confirmed_hz"] = None

    return {"key": state.get("current_bucket"), "db": adjusted_db, "state": state}
