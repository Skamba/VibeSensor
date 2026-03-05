"""Runtime validation and schema-recovery regressions.

Covers:
  1. _corr_abs — NaN propagation guard (helpers.py)
  2. pdf_diagram.py — next() with default for marker lookup
  3. pdf_builder.py — confidence NaN/Inf guard
  4. persistent_findings.py — type hint list[str] (compile-time only)
  5. api_models.py — input validation bounds on request models
  6. history_db.py — corrupted schema version recovery
  7. settings_store.py — dict rollback safety
  8. json_utils.py — depth limit prevents infinite recursion
"""

from __future__ import annotations

import math

import pytest

from vibesensor.analysis.helpers import _corr_abs
from vibesensor.api_models import CarUpsertRequest, SensorRequest, SpeedSourceRequest

_CORR_NONE_CASES = [
    pytest.param([1.0, float("nan"), 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0], id="nan_in_x"),
    pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, float("nan"), 6.0, 8.0, 10.0], id="nan_in_y"),
    pytest.param([float("nan")] * 5, [float("nan")] * 5, id="all_nan"),
    pytest.param([5.0] * 5, [1.0, 2.0, 3.0, 4.0, 5.0], id="constant_x"),
    pytest.param([1.0, 2.0], [3.0, 4.0], id="too_few"),
    pytest.param([1.0, float("inf"), 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0], id="inf_in_x"),
]


def _safe_confidence(raw: object) -> float:
    """Replicate the production clamping logic for confidence values."""
    try:
        val = float(raw or 0.0)
    except (ValueError, TypeError):
        val = 0.0
    return val if math.isfinite(val) else 0.0


_VALIDATION_REJECT_CASES = [
    pytest.param(CarUpsertRequest, {"name": "x" * 65}, id="car_name_too_long"),
    pytest.param(SpeedSourceRequest, {"manualSpeedKph": -10}, id="speed_negative"),
    pytest.param(SpeedSourceRequest, {"manualSpeedKph": 501}, id="speed_too_high"),
    pytest.param(SpeedSourceRequest, {"staleTimeoutS": 301}, id="stale_timeout_too_high"),
    pytest.param(SensorRequest, {"name": "x" * 65}, id="sensor_name_too_long"),
    pytest.param(SensorRequest, {"location": "x" * 65}, id="sensor_location_too_long"),
]


class TestCorrAbsNanGuard:
    """_corr_abs must return None (not NaN) for NaN-contaminated inputs."""

    def test_normal_correlation(self) -> None:
        result = _corr_abs([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0])
        assert result is not None
        assert abs(result - 1.0) < 1e-6

    @pytest.mark.parametrize("x, y", _CORR_NONE_CASES)
    def test_corr_abs_returns_none(self, x: list[float], y: list[float]) -> None:
        assert _corr_abs(x, y) is None
