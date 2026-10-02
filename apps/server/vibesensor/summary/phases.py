"""Driving-phase label keys shared by report and boundary formatting."""

from __future__ import annotations

from typing import Final

PHASE_I18N_KEYS: Final[dict[str, str]] = {
    "idle": "DRIVING_PHASE_IDLE",
    "acceleration": "DRIVING_PHASE_ACCELERATION",
    "cruise": "DRIVING_PHASE_CRUISE",
    "steady": "DRIVING_PHASE_CRUISE",
    "deceleration": "DRIVING_PHASE_DECELERATION",
    "coast_down": "DRIVING_PHASE_COAST_DOWN",
    "speed_unknown": "DRIVING_PHASE_SPEED_UNKNOWN",
}
"""Map persisted driving-phase keys to report/boundary i18n labels."""
