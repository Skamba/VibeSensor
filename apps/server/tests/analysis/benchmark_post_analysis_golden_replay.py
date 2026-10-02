"""Opt-in benchmark for dense golden replay over a realistic 30-minute run."""

from __future__ import annotations

from typing import Any

import pytest
from test_support.golden_replay import (
    benchmark_golden_replay_fixture,
    golden_replay_fixtures,
)

_REALISTIC_DURATION_S = 30 * 60


@pytest.mark.benchmark(group="post-analysis-golden-replay")
def test_post_analysis_golden_replay_30_minute_benchmark(benchmark: Any) -> None:
    fixture = next(
        fixture
        for fixture in golden_replay_fixtures()
        if fixture.case_id == "front-wheel-imbalance"
    )

    result = benchmark.pedantic(
        benchmark_golden_replay_fixture,
        args=(fixture,),
        kwargs={"duration_s": _REALISTIC_DURATION_S},
        iterations=1,
        rounds=1,
        warmup_rounds=0,
    )

    benchmark.extra_info["duration_s"] = _REALISTIC_DURATION_S
    benchmark.extra_info["sensor_count"] = 4
    benchmark.extra_info["peak_memory_bytes"] = result.peak_memory_bytes
    benchmark.extra_info["elapsed_s"] = result.elapsed_s
    assert result.result.manifest.total_window_count >= _REALISTIC_DURATION_S - 1
    assert result.peak_memory_bytes > 0
