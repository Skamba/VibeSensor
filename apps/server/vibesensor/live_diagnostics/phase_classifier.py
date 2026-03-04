"""Driving phase classification from rolling speed history."""

from __future__ import annotations

from collections import deque

from ..analysis import DrivingPhase, classify_sample_phase
from ..constants import MPS_TO_KMH
from ._types import _PHASE_HISTORY_MAX

# Cache enum value strings to avoid repeated attribute access.
_IDLE_VALUE: str = DrivingPhase.IDLE.value

# Local binding avoids module-level attribute lookup on every call.
_classify = classify_sample_phase


class PhaseClassifier:
    """Classifies current driving phase (idle/cruise/accel/decel) from a rolling speed window."""

    __slots__ = ("_speed_history", "_current_phase")

    def __init__(self) -> None:
        self._speed_history: deque[tuple[float, float | None]] = deque(maxlen=_PHASE_HISTORY_MAX)
        self._current_phase: str = _IDLE_VALUE

    def reset(self) -> None:
        self._speed_history.clear()
        self._current_phase = _IDLE_VALUE

    @property
    def current_phase(self) -> str:
        return self._current_phase

    def update(self, speed_mps: float | None, now_s: float) -> None:
        speed_kmh: float | None = speed_mps * MPS_TO_KMH if speed_mps is not None else None
        self._speed_history.append((now_s, speed_kmh))

        # Derive speed derivative from first & last valid entries in the
        # rolling window without building an intermediate filtered list.
        deriv: float | None = None
        first_t = first_s = last_t = last_s = None
        for t, s in self._speed_history:
            if s is not None:
                if first_t is None:
                    first_t = t
                    first_s = s
                last_t = t
                last_s = s
        if first_t is not None and last_t is not None and first_t is not last_t:
            dt = last_t - first_t
            if dt >= 0.1:
                deriv = (last_s - first_s) / dt  # type: ignore[operator]

        self._current_phase = _classify(speed_kmh, deriv).value
