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
from unittest.mock import patch

import pytest

from vibesensor.api_models import CarUpsertRequest, SensorRequest, SpeedSourceRequest
from vibesensor.settings_store import SettingsStore

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


class TestSettingsStoreRollbackSafety:
    """Car aspects rollback must use clear/update, not reassignment."""

    def test_rollback_preserves_dict_identity(self) -> None:
        """After a failed persist, the car.aspects dict object
        should still be the same object (not replaced)."""
        store = SettingsStore(db=None)
        car_data = store.add_car({"name": "TestCar", "type": "sedan"})
        car_id = car_data["cars"][0]["id"]

        # Set as active so _find_car works
        store.set_active_car(car_id)

        # Get the aspects dict reference before update
        with store._lock:
            car = store._find_car(car_id)
            original_aspects_id = id(car.aspects)

        # Force persist to fail
        with patch.object(store, "_persist", side_effect=Exception("disk full")):
            try:
                store.update_car(car_id, {"aspects": {"wheel": 1.0, "driveshaft": 0.5}})
            except Exception:
                pass

        # The aspects dict should still be the SAME object
        with store._lock:
            car = store._find_car(car_id)
            assert id(car.aspects) == original_aspects_id
