"""GPS speed validation policy.

Owns plausibility checks and zero-speed transition confirmation logic,
independent of transport snapshot storage and connection lifecycle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vibesensor.shared.constants.type_checks import NUMERIC_TYPES


@dataclass(frozen=True, slots=True)
class SpeedValidationConfig:
    """Tunable thresholds for GPS speed sample acceptance."""

    max_speed_mps: float = 150.0
    """Reject TPV speed samples above this value (≈ 540 km/h) as implausible."""

    zero_drop_prev_threshold_mps: float = 0.5
    """Previous speed must exceed this to trigger zero-speed confirmation."""

    zero_confirm_samples: int = 3
    """Consecutive zero-speed samples required before accepting the drop."""


DEFAULT_SPEED_VALIDATION_CONFIG = SpeedValidationConfig()


@dataclass(frozen=True, slots=True)
class SpeedSampleVerdict:
    """Result of evaluating a speed sample against the validation policy."""

    accepted: bool
    zero_speed_streak: int


def is_speed_plausible(
    speed_mps: float,
    config: SpeedValidationConfig = DEFAULT_SPEED_VALIDATION_CONFIG,
) -> bool:
    """Return True if *speed_mps* is finite and within the plausible range."""
    return math.isfinite(speed_mps) and 0 <= speed_mps <= config.max_speed_mps


def evaluate_speed_sample(
    speed_mps: float,
    prev_speed: float | None,
    current_streak: int,
    config: SpeedValidationConfig = DEFAULT_SPEED_VALIDATION_CONFIG,
) -> SpeedSampleVerdict:
    """Evaluate whether a zero-speed transition should be accepted.

    When speed drops to 0.0 after a non-trivial previous speed, require
    *config.zero_confirm_samples* consecutive zero readings before accepting.
    All other samples are accepted immediately with the streak reset to 0.
    """
    if speed_mps == 0.0:
        if (
            isinstance(prev_speed, NUMERIC_TYPES)
            and not isinstance(prev_speed, bool)
            and prev_speed > config.zero_drop_prev_threshold_mps
        ):
            streak = current_streak + 1
            return SpeedSampleVerdict(
                accepted=streak >= config.zero_confirm_samples,
                zero_speed_streak=streak,
            )
    return SpeedSampleVerdict(accepted=True, zero_speed_streak=0)
