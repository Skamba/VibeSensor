"""Rows whose speed turns to zero, NaN or negative mid-run still give a finite analysis."""

from __future__ import annotations

import math
from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import ALL_WHEEL_SENSORS, SENSOR_FL, SENSOR_RR, wheel_hz
from test_support.synthetic_samples import make_sample


def _make_speed_scenario_samples(
    *,
    sensors: list[str],
    speed_fn: Any,  # callable(i) -> float
    n_samples: int = 30,
    fault_sensor: str | None = None,
    fault_amp: float = 0.06,
    fault_vib_db: float = 26.0,
    noise_amp: float = 0.004,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Build samples with a custom speed function for each timestep."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = float(i)
        speed = speed_fn(i)
        for sensor in sensors:
            if sensor == fault_sensor and speed > 0:
                whz = wheel_hz(speed) if speed > 0 else 20.0
                peaks: list[dict[str, float]] = [
                    {"hz": whz, "amp": fault_amp},
                    {"hz": whz * 2, "amp": fault_amp * 0.4},
                    {"hz": 142.5, "amp": noise_amp},
                ]
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=fault_vib_db,
                        strength_floor_amp_g=noise_amp,
                    ),
                )
            else:
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=[
                            {"hz": 142.5, "amp": noise_amp},
                            {"hz": 87.3, "amp": noise_amp * 0.8},
                        ],
                        vibration_strength_db=noise_vib_db,
                        strength_floor_amp_g=noise_amp,
                    ),
                )
    return samples


def _assert_no_nan_confidence(summary: dict[str, Any], *, msg: str = "") -> None:
    """Assert no top_cause entry has NaN confidence."""
    for tc in summary.get("top_causes", []):
        conf = float(tc.get("confidence", 0))
        assert not math.isnan(conf), f"NaN confidence{' from ' + msg if msg else ''}"


_CORRUPTION_TYPES = [
    ("zero_second_half", lambda i: 80.0 if i < 15 else 0.0),
    ("nan_second_half", lambda i: 80.0 if i < 15 else float("nan")),
    ("negative_second_half", lambda i: 80.0 if i < 15 else -5.0),
]


@pytest.mark.parametrize(
    ("name", "speed_fn"),
    _CORRUPTION_TYPES,
    ids=[c[0] for c in _CORRUPTION_TYPES],
)
@pytest.mark.parametrize("fault_sensor", [SENSOR_FL, SENSOR_RR], ids=["FL", "RR"])
def test_mixed_valid_invalid_speed(name: str, speed_fn: Any, fault_sensor: str) -> None:
    """Run with partially corrupted speed should still complete analysis."""
    samples = _make_speed_scenario_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_fn=speed_fn,
        n_samples=30,
        fault_sensor=fault_sensor,
    )
    summary = run_analysis(samples)
    assert "top_causes" in summary
    _assert_no_nan_confidence(summary, msg=name)
