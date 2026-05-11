"""Stable facade for generated golden replay fixtures."""

from __future__ import annotations

from test_support.golden_replay_execution import (
    GoldenReplayRecorder,
    benchmark_golden_replay_fixture,
    execute_golden_replay_fixture,
)
from test_support.golden_replay_snapshots import write_golden_replay_snapshot
from test_support.golden_replay_types import (
    GoldenReplayBenchmarkResult,
    GoldenReplayExpected,
    GoldenReplayFixture,
    GoldenReplayResult,
    GoldenReplayRun,
    GoldenScenarioGroup,
    GoldenUnavailableReason,
)


def golden_replay_fixtures(*, fast_ci_only: bool = False) -> tuple[GoldenReplayFixture, ...]:
    from test_support.golden_replay_catalog import golden_replay_fixture_catalog

    fixtures = golden_replay_fixture_catalog()
    if fast_ci_only:
        return tuple(fixture for fixture in fixtures if fixture.fast_ci)
    return fixtures


__all__ = [
    "GoldenReplayBenchmarkResult",
    "GoldenReplayExpected",
    "GoldenReplayFixture",
    "GoldenReplayRecorder",
    "GoldenReplayResult",
    "GoldenReplayRun",
    "GoldenScenarioGroup",
    "GoldenUnavailableReason",
    "benchmark_golden_replay_fixture",
    "execute_golden_replay_fixture",
    "golden_replay_fixtures",
    "write_golden_replay_snapshot",
]
