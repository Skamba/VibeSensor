"""Counter-delta helpers shared across diagnostics and runtime tests."""

from __future__ import annotations


def counter_delta(counter_values: list[float]) -> int:
    """Compute cumulative positive delta from a list of monotonic counter values."""
    if len(counter_values) < 2:
        return 0
    delta = 0.0
    prev = float(counter_values[0])
    for current_raw in counter_values[1:]:
        current = float(current_raw)
        delta += max(0.0, current - prev)
        prev = current
    return int(delta)
