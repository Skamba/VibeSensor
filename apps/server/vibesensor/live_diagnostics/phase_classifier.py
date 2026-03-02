"""Driving phase classification from rolling speed history."""

from __future__ import annotations

from collections import deque

from ..analysis import DrivingPhase, classify_sample_phase
from ..constants import MPS_TO_KMH
from ._types import _PHASE_HISTORY_MAX


class PhaseClassifier:
    """Classifies current driving phase (idle/cruise/accel/decel) from a rolling speed window."""

    __slots__ = ("_speed_history", "_current_phase")

    def __init__(self) -> None:
        self._speed_history: deque[tuple[float, float | None]] = deque(maxlen=_PHASE_HISTORY_MAX)
        self._current_phase: str = DrivingPhase.IDLE.value

    def reset(self) -> None:
        self._speed_history = deque(maxlen=_PHASE_HISTORY_MAX)
        self._current_phase = DrivingPhase.IDLE.value

    @property
    def current_phase(self) -> str:
        return self._current_phase

    def update(self, speed_mps: float | None, now_s: float) -> None:
        speed_kmh: float | None = speed_mps * MPS_TO_KMH if speed_mps is not None else None
        self._speed_history.append((now_s, speed_kmh))
        deriv: float | None = None
        valid = [(t, s) for t, s in self._speed_history if s is not None]
        if len(valid) >= 2:
            t0, s0 = valid[0]
            t1, s1 = valid[-1]
            dt = t1 - t0
            if dt >= 0.1:
                deriv = (s1 - s0) / dt
        self._current_phase = classify_sample_phase(speed_kmh, deriv).value
