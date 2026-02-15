from __future__ import annotations

from math import pi
from threading import RLock

DEFAULT_ANALYSIS_SETTINGS: dict[str, float] = {
    "tire_width_mm": 285.0,
    "tire_aspect_pct": 30.0,
    "rim_in": 21.0,
    "final_drive_ratio": 3.08,
    "current_gear_ratio": 0.64,
}


def tire_circumference_m_from_spec(
    tire_width_mm: float | None,
    tire_aspect_pct: float | None,
    rim_in: float | None,
) -> float | None:
    if tire_width_mm is None or tire_aspect_pct is None or rim_in is None:
        return None
    if tire_width_mm <= 0 or tire_aspect_pct <= 0 or rim_in <= 0:
        return None
    sidewall_mm = tire_width_mm * (tire_aspect_pct / 100.0)
    diameter_mm = (rim_in * 25.4) + (2.0 * sidewall_mm)
    diameter_m = diameter_mm / 1000.0
    if diameter_m <= 0:
        return None
    return diameter_m * pi


class AnalysisSettingsStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._values: dict[str, float] = dict(DEFAULT_ANALYSIS_SETTINGS)

    @staticmethod
    def _sanitize(payload: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key in DEFAULT_ANALYSIS_SETTINGS:
            raw = payload.get(key)
            if raw is None:
                continue
            value = float(raw)
            if value <= 0:
                continue
            out[key] = value
        return out

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    def update(self, payload: dict[str, float]) -> dict[str, float]:
        with self._lock:
            self._values.update(self._sanitize(payload))
            return dict(self._values)

