"""Which guided test-drive steps the drive's speed shows were really done.

The driver taps each step on the Live page; the tap only says when it began.
A step counts as done when the speed inside its window shows it: a sweep
covers a speed range, a hold keeps one speed for a while, a coast-down sheds
speed without the brakes, and the brake step brakes. A step tapped but not
seen in the data is reported as such, and a coast-down that was not one (the
car held its speed) does not decide what the vibration follows.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vibesensor.recording.run_schema import RunGuidedPhase

__all__ = ["guided_step_done"]

# A sweep must cover at least this much of the 50-120 km/h it asks for.
_SWEEP_MIN_SPAN_KMH = 20.0
# A hold: at least this long within this speed band, while really driving (the
# Live page asks for about 20 s; a lagging 1 Hz GPS eats into a short one).
_HOLD_MIN_S = 3.0
_HOLD_MAX_SPAN_KMH = 6.0
_HOLD_MIN_KMH = 20.0
# A coast-down sheds at least this much speed off the brakes.
_COAST_MIN_DROP_KMH = 10.0

type SpeedTrace = Sequence[tuple[float, float]]
type Spans = Sequence[tuple[float, float]]


def guided_step_done(step: RunGuidedPhase, speeds: SpeedTrace, braking: Spans) -> bool:
    """Whether the run's speed inside *step*'s window shows the step was done.

    *speeds* is the run's ``(t_s, speed_kmh)`` trace in time order; *braking*
    the spans the car spent on the brakes.
    """
    end = step.end_t_s if step.end_t_s is not None else float("inf")
    window = [(t_s, kmh) for t_s, kmh in speeds if step.start_t_s <= t_s < end]
    if step.phase == "brake":
        return any(start < end and step.start_t_s < stop for start, stop in braking)
    if not window:
        return False
    if step.phase == "sweep":
        values = [kmh for _t_s, kmh in window]
        return max(values) - min(values) >= _SWEEP_MIN_SPAN_KMH
    if step.phase == "hold":
        return _held(window)
    return _coasted(window, braking)


def _held(window: SpeedTrace) -> bool:
    """Some stretch of the window stays within a narrow speed band long enough.

    A sliding window over the trace, with the running lowest and highest speed
    kept in monotonic queues, so a long open step stays linear.
    """
    lows: deque[int] = deque()
    highs: deque[int] = deque()
    start = 0
    for index, (t_s, kmh) in enumerate(window):
        if kmh < _HOLD_MIN_KMH:
            lows.clear()
            highs.clear()
            start = index + 1
            continue
        while lows and window[lows[-1]][1] >= kmh:
            lows.pop()
        lows.append(index)
        while highs and window[highs[-1]][1] <= kmh:
            highs.pop()
        highs.append(index)
        while window[highs[0]][1] - window[lows[0]][1] > _HOLD_MAX_SPAN_KMH:
            start += 1
            if lows[0] < start:
                lows.popleft()
            if highs[0] < start:
                highs.popleft()
        if t_s - window[start][0] >= _HOLD_MIN_S:
            return True
    return False


def _coasted(window: SpeedTrace, braking: Spans) -> bool:
    """The speed fell far enough between two moments with no braking between them."""
    peak: float | None = None
    peak_t = 0.0
    for t_s, kmh in window:
        braked = any(start < t_s and peak_t < stop for start, stop in braking)
        if peak is None or braked or kmh > peak:
            peak, peak_t = kmh, t_s
            continue
        if peak - kmh >= _COAST_MIN_DROP_KMH:
            return True
    return False
