"""Manual speed payload parsing contracts."""

from __future__ import annotations

import math

import pytest

from vibesensor.shared.types.speed_source_config import SpeedSourceConfig


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(50, 50.0, id="integer-speed"),
        pytest.param(80.5, 80.5, id="float-speed"),
        pytest.param(0.1, 0.1, id="minimum-positive-speed"),
        pytest.param(500, 500.0, id="upper-bound"),
        pytest.param(math.inf, None, id="inf-rejected"),
        pytest.param(-math.inf, None, id="neg-inf-rejected"),
        pytest.param(math.nan, None, id="nan-rejected"),
        pytest.param(-1, None, id="negative-rejected"),
        pytest.param(0, None, id="zero-rejected"),
        pytest.param(500.1, None, id="above-upper-bound-rejected"),
        pytest.param(None, None, id="none-rejected"),
        pytest.param("fast", None, id="string-rejected"),
        pytest.param([], None, id="list-rejected"),
    ],
)
def test_parse_manual_speed_accepts_only_positive_finite_payload_speeds(
    value: object,
    expected: float | None,
) -> None:
    cfg = SpeedSourceConfig.from_dict({"manualSpeedKph": value})
    assert cfg.manual_speed_kph == expected
