# ruff: noqa: E501
"""Order-tracking helpers – wheel/engine/driveshaft Hz, hypotheses, and action plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..analysis_settings import wheel_hz_from_speed_kmh
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from .helpers import _effective_engine_rpm


def _wheel_hz(sample: dict[str, Any], tire_circumference_m: float | None) -> float | None:
    speed_kmh = _as_float(sample.get("speed_kmh"))
    if speed_kmh is None or speed_kmh <= 0:
        return None
    if tire_circumference_m is None or tire_circumference_m <= 0:
        return None
    return wheel_hz_from_speed_kmh(speed_kmh, tire_circumference_m)


def _driveshaft_hz(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
) -> float | None:
    whz = _wheel_hz(sample, tire_circumference_m)
    fd = _as_float(sample.get("final_drive_ratio")) or _as_float(metadata.get("final_drive_ratio"))
    if whz is None or fd is None or fd <= 0:
        return None
    return whz * fd


def _engine_hz(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    rpm, src = _effective_engine_rpm(sample, metadata, tire_circumference_m)
    if rpm is None or rpm <= 0:
        return None, src
    return rpm / 60.0, src


def _order_label(lang: object, order: int, base: str) -> str:
    if normalize_lang(lang) == "nl":
        names = {"wheel": "wielorde", "engine": "motororde", "driveshaft": "aandrijfasorde"}
    else:
        names = {"wheel": "wheel order", "engine": "engine order", "driveshaft": "driveshaft order"}
    return f"{order}x {names.get(base, base)}"


@dataclass(slots=True)
class _OrderHypothesis:
    key: str
    suspected_source: str
    order_label_base: str
    order: int

    def predicted_hz(
        self,
        sample: dict[str, Any],
        metadata: dict[str, Any],
        tire_circumference_m: float | None,
    ) -> tuple[float | None, str]:
        if self.key.startswith("wheel_"):
            base = _wheel_hz(sample, tire_circumference_m)
            return (base * self.order, "speed+tire") if base is not None else (None, "missing")
        if self.key.startswith("driveshaft_"):
            base = _driveshaft_hz(sample, metadata, tire_circumference_m)
            if base is None:
                return None, "missing"
            return base * self.order, "speed+tire+final_drive"
        if self.key.startswith("engine_"):
            base, src = _engine_hz(sample, metadata, tire_circumference_m)
            return (base * self.order, src) if base is not None else (None, "missing")
        return None, "missing"


def _order_hypotheses() -> list[_OrderHypothesis]:
    return [
        _OrderHypothesis("wheel_1x", "wheel/tire", "wheel", 1),
        _OrderHypothesis("wheel_2x", "wheel/tire", "wheel", 2),
        _OrderHypothesis("driveshaft_1x", "driveline", "driveshaft", 1),
        _OrderHypothesis("driveshaft_2x", "driveline", "driveshaft", 2),
        _OrderHypothesis("engine_1x", "engine", "engine", 1),
        _OrderHypothesis("engine_2x", "engine", "engine", 2),
    ]


def _wheel_focus_from_location(lang: object, location: str) -> str:
    token = location.strip().lower()
    if "front-left wheel" in token:
        return _tr(lang, "WHEEL_FOCUS_FRONT_LEFT")
    if "front-right wheel" in token:
        return _tr(lang, "WHEEL_FOCUS_FRONT_RIGHT")
    if "rear-left wheel" in token:
        return _tr(lang, "WHEEL_FOCUS_REAR_LEFT")
    if "rear-right wheel" in token:
        return _tr(lang, "WHEEL_FOCUS_REAR_RIGHT")
    if "rear" in token or "trunk" in token:
        return _tr(lang, "WHEEL_FOCUS_REAR")
    if "front" in token or "engine" in token:
        return _tr(lang, "WHEEL_FOCUS_FRONT")
    return _tr(lang, "WHEEL_FOCUS_ALL")


def _finding_actions_for_source(
    lang: object,
    source: str,
    *,
    strongest_location: str = "",
    strongest_speed_band: str = "",
    weak_spatial_separation: bool = False,
) -> list[dict[str, str]]:
    location = strongest_location.strip()
    speed_band = strongest_speed_band.strip()
    speed_hint = _tr(lang, "SPEED_HINT_FOCUS", speed_band=speed_band) if speed_band else ""
    if source == "wheel/tire":
        wheel_focus = _wheel_focus_from_location(lang, location)
        location_hint = (
            _tr(lang, "LOCATION_HINT_NEAR", location=location)
            if location
            else _tr(lang, "LOCATION_HINT_AT_WHEEL_CORNERS")
        )
        return [
            {
                "action_id": "wheel_balance_and_runout",
                "what": _tr(
                    lang,
                    "ACTION_WHEEL_BALANCE_WHAT",
                    wheel_focus=wheel_focus,
                    speed_hint=speed_hint,
                ),
                "why": _tr(lang, "ACTION_WHEEL_BALANCE_WHY", location_hint=location_hint),
                "confirm": _tr(lang, "ACTION_WHEEL_BALANCE_CONFIRM"),
                "falsify": _tr(lang, "ACTION_WHEEL_BALANCE_FALSIFY"),
                "eta": "20-45 min",
            },
            {
                "action_id": "wheel_tire_condition",
                "what": _tr(lang, "ACTION_TIRE_CONDITION_WHAT", wheel_focus=wheel_focus),
                "why": _tr(lang, "ACTION_TIRE_CONDITION_WHY"),
                "confirm": _tr(lang, "ACTION_TIRE_CONDITION_CONFIRM"),
                "falsify": _tr(lang, "ACTION_TIRE_CONDITION_FALSIFY"),
                "eta": "10-20 min",
            },
        ]
    if source == "driveline":
        driveline_focus = (
            _tr(lang, "LOCATION_HINT_NEAR_SHORT", location=location)
            if location
            else _tr(lang, "LOCATION_HINT_ALONG_DRIVELINE")
        )
        return [
            {
                "action_id": "driveline_inspection",
                "what": _tr(
                    lang, "ACTION_DRIVELINE_INSPECTION_WHAT", driveline_focus=driveline_focus
                ),
                "why": _tr(lang, "ACTION_DRIVELINE_INSPECTION_WHY"),
                "confirm": _tr(lang, "ACTION_DRIVELINE_INSPECTION_CONFIRM"),
                "falsify": _tr(lang, "ACTION_DRIVELINE_INSPECTION_FALSIFY"),
                "eta": "20-35 min",
            },
            {
                "action_id": "driveline_mounts_and_fasteners",
                "what": _tr(lang, "ACTION_DRIVELINE_MOUNTS_WHAT"),
                "why": _tr(lang, "ACTION_DRIVELINE_MOUNTS_WHY"),
                "confirm": _tr(lang, "ACTION_DRIVELINE_MOUNTS_CONFIRM"),
                "falsify": _tr(lang, "ACTION_DRIVELINE_MOUNTS_FALSIFY"),
                "eta": "10-20 min",
            },
        ]
    if source == "engine":
        return [
            {
                "action_id": "engine_mounts_and_accessories",
                "what": _tr(lang, "ACTION_ENGINE_MOUNTS_WHAT"),
                "why": _tr(lang, "ACTION_ENGINE_MOUNTS_WHY"),
                "confirm": _tr(lang, "ACTION_ENGINE_MOUNTS_CONFIRM"),
                "falsify": _tr(lang, "ACTION_ENGINE_MOUNTS_FALSIFY"),
                "eta": "15-30 min",
            },
            {
                "action_id": "engine_combustion_quality",
                "what": _tr(lang, "ACTION_ENGINE_COMBUSTION_WHAT"),
                "why": _tr(lang, "ACTION_ENGINE_COMBUSTION_WHY"),
                "confirm": _tr(lang, "ACTION_ENGINE_COMBUSTION_CONFIRM"),
                "falsify": _tr(lang, "ACTION_ENGINE_COMBUSTION_FALSIFY"),
                "eta": "10-20 min",
            },
        ]
    fallback_why = _tr(lang, "ACTION_GENERAL_FALLBACK_WHY")
    if weak_spatial_separation:
        fallback_why = _tr(lang, "ACTION_GENERAL_WEAK_SPATIAL_WHY")
    return [
        {
            "action_id": "general_mechanical_inspection",
            "what": _tr(lang, "ACTION_GENERAL_INSPECTION_WHAT"),
            "why": fallback_why,
            "confirm": _tr(lang, "ACTION_GENERAL_INSPECTION_CONFIRM"),
            "falsify": _tr(lang, "ACTION_GENERAL_INSPECTION_FALSIFY"),
            "eta": "20-35 min",
        }
    ]
