"""Peak-frequency classification against known vehicle order bands.

Matches a measured peak frequency to wheel, driveshaft, engine, or road-resonance
sources and returns a structured classification result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict

from .constants import (
    FREQUENCY_EPSILON_HZ,
    HARMONIC_2X,
    MIN_OVERLAP_TOLERANCE,
    ROAD_RESONANCE_MAX_HZ,
    ROAD_RESONANCE_MIN_HZ,
)
from .order_bands import build_diagnostic_settings, order_tolerances, vehicle_orders_hz

_INF = float("inf")


class ClassificationResult(TypedDict):
    """Return type of :func:`classify_peak_hz`."""

    key: str
    matched_hz: float | None
    rel_err: float | None
    tol: float | None
    order_label: str | None
    suspected_source: str


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
    """Return the human-readable suspected vibration source for *class_key*."""
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
    """Return the tuple of source system keys associated with *class_key*."""
    return _SOURCE_KEYS.get(class_key, ("other",))


def classify_peak_hz(
    *,
    peak_hz: float,
    speed_mps: float | None,
    settings: Mapping[str, object],
) -> ClassificationResult:
    """Classify *peak_hz* against known vehicle order frequencies.

    Returns a dict with ``class_key``, ``suspected_source``, ``order_label``,
    ``rel_err``, and ``tol`` fields.
    """
    candidates: list[dict[str, float | str]] = []
    order_refs = vehicle_orders_hz(speed_mps=speed_mps, settings=settings)
    resolved_settings = build_diagnostic_settings(settings)
    if order_refs:
        wheel_hz = order_refs["wheel_hz"]
        drive_hz = order_refs["drive_hz"]
        engine_hz = order_refs["engine_hz"]
        wheel_tol, drive_tol, engine_tol = order_tolerances(order_refs, resolved_settings)
        candidates.append({"hz": wheel_hz, "tol": wheel_tol, "key": "wheel1"})
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
                },
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
                },
            )
        else:
            candidates.extend(
                [
                    {"hz": drive_hz, "tol": drive_tol, "key": "shaft1"},
                    {"hz": engine_hz, "tol": engine_tol, "key": "eng1"},
                ],
            )
        candidates.append({"hz": engine_hz * HARMONIC_2X, "tol": engine_tol, "key": "eng2"})

    best: dict[str, float | str] | None = None
    best_err = _INF
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
        return _unmatched_classification("road")
    return _unmatched_classification("other")


def _unmatched_classification(key: str) -> ClassificationResult:
    """Return a classification result for a peak that did not match any order band."""
    return {
        "key": key,
        "matched_hz": None,
        "rel_err": None,
        "tol": None,
        "order_label": None,
        "suspected_source": suspected_source_from_class_key(key),
    }
