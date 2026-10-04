"""Sliding-window event counts."""

from __future__ import annotations

from vibesensor.common.recent_counter import RecentCounter


def test_counts_only_events_inside_the_window() -> None:
    counter = RecentCounter(window_s=60.0)
    counter.add(2, 100.2)
    counter.add(3, 100.7)  # same one-second bucket
    counter.add(0, 120.0)  # ignored
    counter.add(5, 130.0)

    assert counter.total(130.0) == 10
    assert counter.total(160.5) == 10
    # The 100 s bucket ends at 101 s, which is outside a 60 s window at 161 s.
    assert counter.total(161.0) == 5
    assert counter.total(191.0) == 0

    counter.add(1, 200.0)
    counter.clear()
    assert counter.total(200.0) == 0
