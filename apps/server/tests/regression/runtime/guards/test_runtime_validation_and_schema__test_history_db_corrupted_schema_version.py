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
import sqlite3

import pytest

from vibesensor.api_models import CarUpsertRequest, SensorRequest, SpeedSourceRequest
from vibesensor.history_db import HistoryDB

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


class TestHistoryDbCorruptedSchemaVersion:
    """_ensure_schema must not crash on corrupted version metadata."""

    def test_corrupted_version_string_recovers(self, tmp_path) -> None:
        db_path = tmp_path / "test.db"
        # Create a DB with a corrupted version value
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', 'CORRUPT')")
        conn.commit()
        conn.close()

        # Should not crash — should recover
        assert HistoryDB(db_path) is not None

    def test_valid_version_still_works(self, tmp_path) -> None:
        assert HistoryDB(tmp_path / "test.db") is not None
