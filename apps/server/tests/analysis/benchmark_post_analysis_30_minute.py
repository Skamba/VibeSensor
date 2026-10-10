"""Opt-in benchmark: post-analysis time and peak memory for a 30-minute recording.

A 30-minute simulated drive (the recording cap) with a front-left wheel
imbalance goes through the real pipeline; the benchmark measures the
post-analysis that runs when it stops, which is the Pi's memory high-water mark.
Recording the drive takes a few minutes of wall time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_support.sim_pipeline import BenchCar, BenchSensor, run_sim_pipeline

from vibesensor.recording.lifecycle_state import MAX_RECORDING_DURATION_S
from vibesensor.simulator.scripted_scenario_models import PhaseOverride, ScenarioPhase

_CAR = BenchCar("Default car", 285.0, 30.0, 21.0, 3.08, 0.64)
_SENSORS = (
    BenchSensor("VS-12 front left", "front_left_wheel"),
    BenchSensor("VS-25 front right", "front_right_wheel"),
    BenchSensor("VS-33 rear left", "rear_left_wheel"),
    BenchSensor("VS-41 rear right", "rear_right_wheel"),
)
_OVERRIDES = (
    PhaseOverride("all", "rough_road", 0.28, 1.0, 0.52, 1.0),
    PhaseOverride("front-left", "wheel_imbalance", 0.85, 1.0, 1.0, 1.0),
)
# Up and down between 60 and 120 km/h, minus a margin so the cap does not stop it.
_LEG_S = 120.0
_PHASES = tuple(
    ScenarioPhase(
        name=f"leg-{index}",
        duration_s=_LEG_S,
        speed_start_kmh=60.0 if index % 2 == 0 else 120.0,
        speed_end_kmh=120.0 if index % 2 == 0 else 60.0,
        overrides=_OVERRIDES,
    )
    for index in range(int((MAX_RECORDING_DURATION_S - 30.0) // _LEG_S))
)


# Recording the drive plus traced post-analysis takes ~3 minutes on x86, past the
# suite-wide 120 s timeout; this opt-in benchmark gets its own budget.
@pytest.mark.timeout(600)
@pytest.mark.benchmark(group="post-analysis-30-minute")
def test_post_analysis_30_minute_benchmark(benchmark: Any, tmp_path: Path) -> None:
    result = benchmark.pedantic(
        run_sim_pipeline,
        args=(tmp_path,),
        kwargs={
            "car": _CAR,
            "sensors": _SENSORS,
            "scenario_name": "benchmark-30-minute",
            "phases": _PHASES,
            "client_seed": 1,
            "trace_post_analysis_memory": True,
        },
        iterations=1,
        rounds=1,
        warmup_rounds=0,
    )
    try:
        benchmark.extra_info["drive_s"] = sum(phase.duration_s for phase in _PHASES)
        benchmark.extra_info["sensor_count"] = len(_SENSORS)
        benchmark.extra_info["post_analysis_s"] = result.post_analysis_s
        benchmark.extra_info["post_analysis_peak_bytes"] = result.post_analysis_peak_bytes
        assert result.diagnosis["source"] == "wheel/tire"
        assert result.diagnosis["zone"] == "front_left_wheel"
    finally:
        result.history_db.close()
