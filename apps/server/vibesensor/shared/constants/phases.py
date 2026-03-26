"""Driving-phase label keys shared by report and boundary formatting."""

from __future__ import annotations

from typing import Final

PHASE_I18N_KEYS: Final[dict[str, str]] = {
    "acceleration": "DRIVING_PHASE_ACCELERATION",
    "deceleration": "DRIVING_PHASE_DECELERATION",
    "coast_down": "DRIVING_PHASE_COAST_DOWN",
}
"""Map persisted driving-phase keys to report/boundary i18n labels."""
