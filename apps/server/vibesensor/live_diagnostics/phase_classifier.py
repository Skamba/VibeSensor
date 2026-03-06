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
        """Clear speed history and return to ``idle`` phase."""
        self._speed_history.clear()
        self._current_phase = _IDLE_VALUE

    @property
    def current_phase(self) -> str:
        """Return the current driving phase string (e.g. ``"idle"``, ``"cruise"``)."""
        return self._current_phase

    @property
    def speed_history(self) -> deque[tuple[float, float | None]]:
        """Read/write access to the rolling speed history (for testing and inspection)."""
        return self._speed_history

    @speed_history.setter
    def speed_history(self, value: deque[tuple[float, float | None]]) -> None:
        self._speed_history = value

    def update(self, speed_mps: float | None, now_s: float) -> None:
        """Add a new speed sample, re-derive the rolling phase, and update ``current_phase``."""
        speed_kmh: float | None = speed_mps * MPS_TO_KMH if speed_mps is not None else None
        self._speed_history.append((now_s, speed_kmh))

        # Derive speed derivative from first & last valid entries in the
        # rolling window without building an intermediate filtered list.
        deriv: float | None = None
        first_t: float | None = None
        first_s: float | None = None
        last_t: float | None = None
        last_s: float | None = None
        for t, s in self._speed_history:
            if s is not None:
                if first_t is None:
                    first_t = t
                    first_s = s
                last_t = t
                last_s = s
        if (
            first_t is not None
            and first_s is not None
            and last_t is not None
            and last_s is not None
            and first_t is not last_t
        ):
            dt = last_t - first_t
            if dt >= 0.1:
                deriv = (last_s - first_s) / dt

        self._current_phase = _classify(speed_kmh, deriv).value
