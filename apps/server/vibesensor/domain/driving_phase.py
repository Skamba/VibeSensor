"""Driving-phase enum — a genuine domain concept.

``DrivingPhase`` classifies the driving condition during a segment of a
diagnostic run.  The ``AnalysisWindow`` dataclass that uses this enum
lives in the analysis layer (``vibesensor.analysis.analysis_window``)
because its fields (``start_idx``/``end_idx``) are array-index
implementation details of the pipeline, not domain vocabulary.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "DrivingPhase",
]


class DrivingPhase(StrEnum):
    """Canonical driving-phase labels."""

    IDLE = "idle"
    ACCELERATION = "acceleration"
    CRUISE = "cruise"
    DECELERATION = "deceleration"
    COAST_DOWN = "coast_down"
    SPEED_UNKNOWN = "speed_unknown"
