"""A tapped guided step counts as done only when the drive's speed shows it."""

from __future__ import annotations

import pytest

from vibesensor.analysis.guided_steps import guided_step_done
from vibesensor.recording.run_schema import RunGuidedPhase


def _trace(*speeds: float) -> list[tuple[float, float]]:
    return [(float(t_s), kmh) for t_s, kmh in enumerate(speeds)]


_STEADY_50 = _trace(*[50.0] * 12)
_RAMP_50_TO_90 = _trace(*[50.0 + 4.0 * i for i in range(11)])
_ROLL_80_TO_60 = _trace(80.0, 80.0, 78.0, 75.0, 72.0, 69.0, 66.0, 63.0, 60.0)
_BRAKED_80_TO_60 = (2.0, 7.0)


@pytest.mark.parametrize(
    ("phase", "speeds", "braking", "done"),
    [
        ("sweep", _RAMP_50_TO_90, (), True),
        ("sweep", _STEADY_50, (), False),
        ("hold", _STEADY_50, (), True),
        ("hold", _RAMP_50_TO_90, (), False),
        # Standing still is not a hold, however steady.
        ("hold", _trace(*[0.0] * 12), (), False),
        # A hold that drifts a little but stays in its band still counts.
        ("hold", _trace(48, 50, 52, 51, 49, 53, 50, 90), (), True),
        ("coast_down", _ROLL_80_TO_60, (), True),
        ("coast_down", _STEADY_50, (), False),
        # Shedding speed on the brakes is not a coast-down.
        ("coast_down", _ROLL_80_TO_60, (_BRAKED_80_TO_60,), False),
        ("brake", _ROLL_80_TO_60, (_BRAKED_80_TO_60,), True),
        ("brake", _STEADY_50, (), False),
    ],
)
def test_a_tapped_step_is_done_only_when_the_speed_shows_it(
    phase: str, speeds: list[tuple[float, float]], braking: tuple, done: bool
) -> None:
    step = RunGuidedPhase(phase=phase, start_t_s=0.0, end_t_s=None)
    assert guided_step_done(step, speeds, braking) is done


def test_only_the_steps_own_window_counts() -> None:
    # The ramp happened, but before the sweep was tapped.
    speeds = [*_RAMP_50_TO_90, *((11.0 + i, 90.0) for i in range(10))]
    late = RunGuidedPhase(phase="sweep", start_t_s=11.0, end_t_s=None)
    assert not guided_step_done(late, speeds, ())
    assert guided_step_done(RunGuidedPhase(phase="sweep", start_t_s=0.0, end_t_s=11.0), speeds, ())
