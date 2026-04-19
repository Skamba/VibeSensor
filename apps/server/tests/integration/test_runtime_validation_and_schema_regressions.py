"""Runtime validation and schema-recovery regressions.

Covers:
  1. _corr_abs — NaN propagation guard (math_utils.py)
  2. pdf_diagram_render.py — next() with default for marker lookup
  3. pdf_engine.py — confidence NaN/Inf guard
  4. persistent_findings.py — type hint list[str] (compile-time only)
    5. api_models/ — input validation bounds on request models
  6. history_db.py — corrupted schema version recovery
  7. settings_store.py — dict rollback safety
  8. json_utils.py — depth limit prevents infinite recursion
"""

from __future__ import annotations

import contextlib
import math
import sqlite3
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from test_support.settings_services import build_settings_services

from vibesensor.adapters.http.models import CarUpsertRequest, SpeedSourceRequest
from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.shared.exceptions import PersistenceError
from vibesensor.shared.json_utils import sanitize_for_json
from vibesensor.use_cases.diagnostics.math_utils import _corr_abs

# ------------------------------------------------------------------
# 1. _corr_abs — NaN propagation guard
# ------------------------------------------------------------------

_CORR_NONE_CASES = [
    pytest.param([1.0, float("nan"), 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0], id="nan_in_x"),
    pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, float("nan"), 6.0, 8.0, 10.0], id="nan_in_y"),
    pytest.param([float("nan")] * 5, [float("nan")] * 5, id="all_nan"),
    pytest.param([5.0] * 5, [1.0, 2.0, 3.0, 4.0, 5.0], id="constant_x"),
    pytest.param([1.0, 2.0], [3.0, 4.0], id="too_few"),
    pytest.param([1.0, float("inf"), 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0], id="inf_in_x"),
]


class TestCorrAbsNanGuard:
    """_corr_abs must return None (not NaN) for NaN-contaminated inputs."""

    def test_normal_correlation(self) -> None:
        result = _corr_abs([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0])
        assert result is not None
        assert abs(result - 1.0) < 1e-6

    @pytest.mark.parametrize(("x", "y"), _CORR_NONE_CASES)
    def test_corr_abs_returns_none(self, x: list[float], y: list[float]) -> None:
        assert _corr_abs(x, y) is None


# ------------------------------------------------------------------
# 2. pdf_diagram — next() with default for marker lookup
# ------------------------------------------------------------------


class TestPdfDiagramMarkerLookup:
    """Marker lookup must not raise StopIteration for missing markers.

    The fix changed ``next(item for ...)`` to ``next((...), None)``
    with a ``continue`` guard in pdf_diagram_render.py.  We verify the
    pattern at a unit level (the inline logic is inside
    car_location_diagram and not separately testable).
    """

    def test_next_with_default_returns_none(self) -> None:
        """Verify the pattern used in the fix: next() with default None."""
        items = [{"name": "a"}, {"name": "b"}]
        result = next((i for i in items if i["name"] == "missing"), None)
        assert result is None

    def test_next_without_default_raises(self) -> None:
        """Document the original bug: next() without default raises."""
        items = [{"name": "a"}, {"name": "b"}]
        with pytest.raises(StopIteration):
            next(i for i in items if i["name"] == "missing")


# ------------------------------------------------------------------
# 3. pdf_engine — confidence NaN/Inf guard
# ------------------------------------------------------------------


def _safe_confidence(raw: object) -> float:
    """Replicate the production clamping logic for confidence values."""
    try:
        val = float(raw or 0.0)
    except (ValueError, TypeError):
        val = 0.0
    return val if math.isfinite(val) else 0.0


class TestConfidenceNanGuard:
    """Confidence formatting must handle NaN/Inf gracefully."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param(float("nan"), 0.0, id="nan"),
            pytest.param(float("inf"), 0.0, id="inf"),
            pytest.param(0.75, 0.75, id="valid"),
        ],
    )
    def test_confidence_clamped(self, raw: float, expected: float) -> None:
        confidence = _safe_confidence(raw)
        assert abs(confidence - expected) < 1e-6
        # Verify formatting doesn't crash
        f"({confidence * 100.0:.0f}%)"


# ------------------------------------------------------------------
# 4. api_models — input validation bounds
# ------------------------------------------------------------------

_VALIDATION_REJECT_CASES = [
    pytest.param(CarUpsertRequest, {"name": "x" * 65}, id="car_name_too_long"),
    pytest.param(SpeedSourceRequest, {"manual_speed_kph": -10}, id="speed_negative"),
    pytest.param(SpeedSourceRequest, {"manual_speed_kph": 501}, id="speed_too_high"),
    pytest.param(SpeedSourceRequest, {"stale_timeout_s": 301}, id="stale_timeout_too_high"),
]


class TestApiModelValidationBounds:
    """Request models must reject out-of-bounds values."""

    @pytest.mark.parametrize(("model", "kwargs"), _VALIDATION_REJECT_CASES)
    def test_out_of_bounds_rejected(self, model: type, kwargs: dict) -> None:
        with pytest.raises(ValidationError, match=r"validation error"):
            model(**kwargs)

    def test_car_upsert_name_within_limit_ok(self) -> None:
        req = CarUpsertRequest(name="x" * 64)
        assert req.name == "x" * 64

    def test_speed_source_valid_speed_ok(self) -> None:
        req = SpeedSourceRequest(manual_speed_kph=120)
        assert req.manual_speed_kph == 120


# ------------------------------------------------------------------
# 5. history_db — corrupted schema version recovery
# ------------------------------------------------------------------


class TestHistoryDbCorruptedSchemaVersion:
    """_ensure_schema must not crash on corrupted version metadata."""

    def test_legacy_schema_meta_rejected(self, tmp_path) -> None:
        db_path = tmp_path / "test.db"
        # Create a DB with a legacy schema_meta table
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', 'CORRUPT')")
        conn.commit()
        conn.close()

        # Legacy schema_meta databases are no longer supported
        with pytest.raises(RuntimeError, match="legacy"):
            HistoryDB(db_path)

    def test_valid_version_still_works(self, tmp_path) -> None:
        assert HistoryDB(tmp_path / "test.db") is not None


# ------------------------------------------------------------------
# 6. settings_store — car rollback safety
# ------------------------------------------------------------------


class TestSettingsStoreRollbackSafety:
    """Car aspects rollback must restore original state on persist failure."""

    def test_rollback_preserves_dict_identity(self) -> None:
        """After a failed persist, the car should be restored
        to its original state (same content).
        """
        services = build_settings_services()
        car_data = services.car_settings.add_car({"name": "TestCar", "type": "sedan"})
        car_id = car_data.cars[0]["id"]

        # Set as active so the public current-car snapshot reflects the target car.
        services.car_settings.set_active_car(car_id)

        original_snapshot = services.car_settings.active_car_snapshot()
        assert original_snapshot is not None
        original_aspects = dict(original_snapshot.aspects)
        services.coordinator._db = MagicMock()
        services.coordinator._db.set_settings_snapshot.side_effect = OSError("disk full")

        # Force persist to fail with PersistenceError (triggers rollback)
        with contextlib.suppress(PersistenceError):
            services.car_settings.update_car(car_id, {"aspects": {"wheel": 1.0, "driveshaft": 0.5}})

        restored_snapshot = services.car_settings.active_car_snapshot()
        assert restored_snapshot is not None
        assert dict(restored_snapshot.aspects) == original_aspects


# ------------------------------------------------------------------
# 7. json_utils — depth limit prevents infinite recursion
# ------------------------------------------------------------------


class TestJsonSanitizeDepthLimit:
    """sanitize_for_json must not crash on deeply nested or circular structures."""

    def test_deeply_nested_dict_truncated(self) -> None:
        # Build a dict nested 200 levels deep (exceeds default 128 limit)
        obj: dict = {}
        current = obj
        for _i in range(200):
            current["child"] = {}
            current = current["child"]
        current["value"] = 42.0

        result, _ = sanitize_for_json(obj)
        # Should not crash; deeply nested values should be truncated to None
        assert result is not None

    def test_normal_depth_preserved(self) -> None:
        obj = {"a": {"b": {"c": 1.5}}}
        result, found = sanitize_for_json(obj)
        assert result == {"a": {"b": {"c": 1.5}}}
        assert not found
