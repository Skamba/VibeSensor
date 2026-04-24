"""Deterministic whole-run window planning over persisted run metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunWindowDescriptor,
    WholeRunWindowPolicy,
)

type TrailingWindowPolicy = Literal["drop_incomplete_trailing"]

__all__ = [
    "TrailingWindowPolicy",
    "WholeRunWindowPlan",
    "plan_whole_run_window_range",
    "plan_whole_run_windows",
]


@dataclass(frozen=True, slots=True)
class WholeRunWindowPlan:
    """Deterministic whole-run window grid shared by later offline analysis stages."""

    policy: WholeRunWindowPolicy
    coverage_sample_start: int
    coverage_sample_end: int
    windows: tuple[WholeRunWindowDescriptor, ...]
    trailing_window_policy: TrailingWindowPolicy = "drop_incomplete_trailing"

    @property
    def total_sample_count(self) -> int:
        return max(0, self.coverage_sample_end - self.coverage_sample_start)

    @property
    def total_window_count(self) -> int:
        return len(self.windows)

    @property
    def expected_sensor_sample_count(self) -> int:
        return self.policy.window_size_samples

    @property
    def expected_sensor_coverage_start(self) -> int | None:
        if not self.windows:
            return None
        return self.windows[0].sample_start

    @property
    def expected_sensor_coverage_end(self) -> int | None:
        if not self.windows:
            return None
        return self.windows[-1].sample_end

    @property
    def dropped_trailing_samples(self) -> int:
        expected_end = self.expected_sensor_coverage_end
        if expected_end is None:
            return self.total_sample_count
        return max(0, self.coverage_sample_end - expected_end)

    def window(self, window_index: int) -> WholeRunWindowDescriptor | None:
        if window_index < 0 or window_index >= len(self.windows):
            return None
        return self.windows[window_index]


def plan_whole_run_windows(
    *,
    metadata: RunMetadata,
    total_sample_count: int,
) -> WholeRunWindowPlan:
    """Return the canonical whole-run window grid for one persisted run."""

    if total_sample_count < 0:
        raise ValueError("whole-run window planner requires total_sample_count >= 0")
    return plan_whole_run_window_range(
        metadata=metadata,
        coverage_sample_start=0,
        coverage_sample_end=total_sample_count,
    )


def plan_whole_run_window_range(
    *,
    metadata: RunMetadata,
    coverage_sample_start: int,
    coverage_sample_end: int,
) -> WholeRunWindowPlan:
    """Return the canonical whole-run window grid for one shared sample-time range."""

    if coverage_sample_start < 0:
        raise ValueError("whole-run window planner requires coverage_sample_start >= 0")
    if coverage_sample_end < coverage_sample_start:
        raise ValueError(
            "whole-run window planner requires coverage_sample_end >= coverage_sample_start"
        )
    policy = WholeRunWindowPolicy.from_metadata(metadata)
    coverage_sample_count = coverage_sample_end - coverage_sample_start
    if coverage_sample_count < policy.window_size_samples:
        return WholeRunWindowPlan(
            policy=policy,
            coverage_sample_start=coverage_sample_start,
            coverage_sample_end=coverage_sample_end,
            windows=(),
        )
    max_sample_start = coverage_sample_end - policy.window_size_samples
    windows = tuple(
        WholeRunWindowDescriptor.from_policy(
            window_index=window_index,
            sample_start=sample_start,
            policy=policy,
        )
        for window_index, sample_start in enumerate(
            range(coverage_sample_start, max_sample_start + 1, policy.stride_samples)
        )
    )
    return WholeRunWindowPlan(
        policy=policy,
        coverage_sample_start=coverage_sample_start,
        coverage_sample_end=coverage_sample_end,
        windows=windows,
    )
