from __future__ import annotations

from collections.abc import Mapping
from math import log10, sqrt
from typing import Any

from .analysis_settings import tire_circumference_m_from_spec

DEFAULT_DIAGNOSTIC_SETTINGS: dict[str, float] = {
    "tire_width_mm": 285.0,
    "tire_aspect_pct": 30.0,
    "rim_in": 21.0,
    "final_drive_ratio": 3.08,
    "current_gear_ratio": 0.64,
    "wheel_bandwidth_pct": 6.0,
    "driveshaft_bandwidth_pct": 5.6,
    "engine_bandwidth_pct": 6.2,
    "speed_uncertainty_pct": 0.6,
    "tire_diameter_uncertainty_pct": 1.2,
    "final_drive_uncertainty_pct": 0.2,
    "gear_uncertainty_pct": 0.5,
    "min_abs_band_hz": 0.4,
    "max_band_half_width_pct": 8.0,
}

ORDER_CLASS_KEYS = {"wheel1", "wheel2", "shaft_eng1", "shaft1", "eng1", "eng2"}


def _as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def build_diagnostic_settings(overrides: Mapping[str, Any] | None = None) -> dict[str, float]:
    out = dict(DEFAULT_DIAGNOSTIC_SETTINGS)
    if not overrides:
        return out
    for key in DEFAULT_DIAGNOSTIC_SETTINGS:
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


def vehicle_orders_hz(
    *,
    speed_mps: float | None,
    settings: Mapping[str, Any],
) -> dict[str, float] | None:
    if speed_mps is None or speed_mps <= 0:
        return None
    spec_settings = build_diagnostic_settings(settings)
    circumference = tire_circumference_m_from_spec(
        _as_float(spec_settings.get("tire_width_mm")),
        _as_float(spec_settings.get("tire_aspect_pct")),
        _as_float(spec_settings.get("rim_in")),
    )
    if circumference is None or circumference <= 0:
        return None
    final_drive_ratio = _as_float(spec_settings.get("final_drive_ratio"))
    gear_ratio = _as_float(spec_settings.get("current_gear_ratio"))
    if final_drive_ratio is None or final_drive_ratio <= 0 or gear_ratio is None or gear_ratio <= 0:
        return None

    wheel_hz = speed_mps / circumference
    drive_hz = wheel_hz * final_drive_ratio
    engine_hz = drive_hz * gear_ratio
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


def _order_label_for_class_key(class_key: str) -> str | None:
    if class_key == "wheel1":
        return "1x wheel order"
    if class_key == "wheel2":
        return "2x wheel order"
    if class_key == "shaft_eng1":
        return "1x driveshaft/engine order"
    if class_key == "shaft1":
        return "1x driveshaft order"
    if class_key == "eng1":
        return "1x engine order"
    if class_key == "eng2":
        return "2x engine order"
    return None


def suspected_source_from_class_key(class_key: str) -> str:
    if class_key in {"wheel1", "wheel2"}:
        return "wheel/tire"
    if class_key in {"shaft1", "shaft_eng1"}:
        return "driveline"
    if class_key in {"eng1", "eng2"}:
        return "engine"
    if class_key == "road":
        return "body resonance"
    return "unknown"


def source_keys_from_class_key(class_key: str) -> tuple[str, ...]:
    if class_key == "shaft_eng1":
        return ("driveshaft", "engine")
    if class_key in {"eng1", "eng2"}:
        return ("engine",)
    if class_key == "shaft1":
        return ("driveshaft",)
    if class_key in {"wheel1", "wheel2"}:
        return ("wheel",)
    return ("other",)


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
        wheel_tol = tolerance_for_order(
            resolved_settings["wheel_bandwidth_pct"],
            wheel_hz,
            order_refs["wheel_uncertainty_pct"],
            min_abs_band_hz=resolved_settings["min_abs_band_hz"],
            max_band_half_width_pct=resolved_settings["max_band_half_width_pct"],
        )
        drive_tol = tolerance_for_order(
            resolved_settings["driveshaft_bandwidth_pct"],
            drive_hz,
            order_refs["drive_uncertainty_pct"],
            min_abs_band_hz=resolved_settings["min_abs_band_hz"],
            max_band_half_width_pct=resolved_settings["max_band_half_width_pct"],
        )
        engine_tol = tolerance_for_order(
            resolved_settings["engine_bandwidth_pct"],
            engine_hz,
            order_refs["engine_uncertainty_pct"],
            min_abs_band_hz=resolved_settings["min_abs_band_hz"],
            max_band_half_width_pct=resolved_settings["max_band_half_width_pct"],
        )
        candidates.extend(
            [
                {"hz": wheel_hz, "tol": wheel_tol, "key": "wheel1"},
                {"hz": wheel_hz * 2.0, "tol": wheel_tol, "key": "wheel2"},
            ]
        )
        overlap_tol = max(
            0.03,
            order_refs["drive_uncertainty_pct"] + order_refs["engine_uncertainty_pct"],
        )
        if abs(drive_hz - engine_hz) / max(1e-6, engine_hz) < overlap_tol:
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
        candidates.append({"hz": engine_hz * 2.0, "tol": engine_tol, "key": "eng2"})

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
    if 3.0 <= peak_hz <= 12.0:
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


SEVERITY_BANDS: tuple[tuple[str, float, float], ...] = (
    ("l5", 40.0, float("inf")),
    ("l4", 34.0, 40.0),
    ("l3", 28.0, 34.0),
    ("l2", 22.0, 28.0),
    ("l1", 16.0, 22.0),
)


def severity_from_peak(
    *,
    peak_amp: float,
    floor_amp: float,
    sensor_count: int,
) -> dict[str, float | str] | None:
    if peak_amp <= 0:
        return None
    db = 20.0 * log10((max(0.0, peak_amp) + 1.0) / (max(0.0, floor_amp) + 1.0))
    adjusted_db = db + 2.0 if sensor_count >= 2 else db
    for key, min_db, max_db in SEVERITY_BANDS:
        if adjusted_db >= min_db and adjusted_db < max_db:
            return {"key": key, "db": adjusted_db}
    return None
