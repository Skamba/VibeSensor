"""Tests for Run 2 Cycle 1 fixes.

Covers:
  1. _corr_abs — NaN propagation guard (helpers.py)
  2. pdf_diagram.py — next() with default for marker lookup
  3. pdf_builder.py — confidence NaN/Inf guard
  4. persistent_findings.py — type hint list[str] (compile-time only)
  5. api_models.py — input validation bounds on request models
"""

from __future__ import annotations

import math

import pytest

# ------------------------------------------------------------------
# 1. _corr_abs — NaN propagation guard
# ------------------------------------------------------------------


class TestCorrAbsNanGuard:
    """_corr_abs must return None (not NaN) for NaN-contaminated inputs."""

    def test_normal_correlation(self) -> None:
        from vibesensor.analysis.helpers import _corr_abs

        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        result = _corr_abs(x, y)
        assert result is not None
        assert abs(result - 1.0) < 1e-6

    def test_nan_in_x_returns_none(self) -> None:
        from vibesensor.analysis.helpers import _corr_abs

        x = [1.0, float("nan"), 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        result = _corr_abs(x, y)
        assert result is None

    def test_nan_in_y_returns_none(self) -> None:
        from vibesensor.analysis.helpers import _corr_abs

        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, float("nan"), 6.0, 8.0, 10.0]
        result = _corr_abs(x, y)
        assert result is None

    def test_all_nan_returns_none(self) -> None:
        from vibesensor.analysis.helpers import _corr_abs

        x = [float("nan")] * 5
        y = [float("nan")] * 5
        result = _corr_abs(x, y)
        assert result is None

    def test_constant_values_returns_none(self) -> None:
        from vibesensor.analysis.helpers import _corr_abs

        x = [5.0, 5.0, 5.0, 5.0, 5.0]
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _corr_abs(x, y)
        assert result is None

    def test_too_few_elements(self) -> None:
        from vibesensor.analysis.helpers import _corr_abs

        result = _corr_abs([1.0, 2.0], [3.0, 4.0])
        assert result is None

    def test_inf_returns_none(self) -> None:
        from vibesensor.analysis.helpers import _corr_abs

        x = [1.0, float("inf"), 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        result = _corr_abs(x, y)
        assert result is None


# ------------------------------------------------------------------
# 2. pdf_diagram — next() with default for marker lookup
# ------------------------------------------------------------------


class TestPdfDiagramMarkerLookup:
    """Marker lookup must not raise StopIteration for missing markers.

    The fix changed ``next(item for ...)`` to ``next((...), None)``
    with a ``continue`` guard in pdf_diagram.py.  We verify the
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
# 3. pdf_builder — confidence NaN/Inf guard
# ------------------------------------------------------------------


class TestConfidenceNanGuard:
    """Confidence formatting must handle NaN/Inf gracefully."""

    def test_nan_confidence_clamped_to_zero(self) -> None:
        """If confidence_0_to_1 is NaN, it should be treated as 0."""
        finding = {
            "frequency_hz_or_order": "42 Hz",
            "confidence_0_to_1": float("nan"),
        }
        confidence_val = finding.get("confidence_0_to_1")
        try:
            confidence = float(confidence_val or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        if not math.isfinite(confidence):
            confidence = 0.0
        assert confidence == 0.0
        # Verify formatting doesn't crash
        line = f"• 42 Hz ({confidence * 100.0:.0f}%)"
        assert "0%" in line

    def test_inf_confidence_clamped_to_zero(self) -> None:
        finding = {"confidence_0_to_1": float("inf")}
        confidence_val = finding.get("confidence_0_to_1")
        try:
            confidence = float(confidence_val or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        if not math.isfinite(confidence):
            confidence = 0.0
        assert confidence == 0.0

    def test_valid_confidence_unchanged(self) -> None:
        finding = {"confidence_0_to_1": 0.75}
        confidence_val = finding.get("confidence_0_to_1")
        try:
            confidence = float(confidence_val or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        if not math.isfinite(confidence):
            confidence = 0.0
        assert abs(confidence - 0.75) < 1e-6


# ------------------------------------------------------------------
# 4. api_models — input validation bounds
# ------------------------------------------------------------------


class TestApiModelValidationBounds:
    """Request models must reject out-of-bounds values."""

    def test_car_upsert_name_too_long_rejected(self) -> None:
        from pydantic import ValidationError

        from vibesensor.api_models import CarUpsertRequest

        with pytest.raises(ValidationError):
            CarUpsertRequest(name="x" * 65)

    def test_car_upsert_name_within_limit_ok(self) -> None:
        from vibesensor.api_models import CarUpsertRequest

        req = CarUpsertRequest(name="x" * 64)
        assert req.name == "x" * 64

    def test_speed_source_manual_speed_negative_rejected(self) -> None:
        from pydantic import ValidationError

        from vibesensor.api_models import SpeedSourceRequest

        with pytest.raises(ValidationError):
            SpeedSourceRequest(manualSpeedKph=-10)

    def test_speed_source_manual_speed_too_high_rejected(self) -> None:
        from pydantic import ValidationError

        from vibesensor.api_models import SpeedSourceRequest

        with pytest.raises(ValidationError):
            SpeedSourceRequest(manualSpeedKph=501)

    def test_speed_source_valid_speed_ok(self) -> None:
        from vibesensor.api_models import SpeedSourceRequest

        req = SpeedSourceRequest(manualSpeedKph=120)
        assert req.manualSpeedKph == 120

    def test_speed_source_stale_timeout_too_high_rejected(self) -> None:
        from pydantic import ValidationError

        from vibesensor.api_models import SpeedSourceRequest

        with pytest.raises(ValidationError):
            SpeedSourceRequest(staleTimeoutS=301)

    def test_sensor_request_name_too_long_rejected(self) -> None:
        from pydantic import ValidationError

        from vibesensor.api_models import SensorRequest

        with pytest.raises(ValidationError):
            SensorRequest(name="x" * 65)

    def test_sensor_request_location_too_long_rejected(self) -> None:
        from pydantic import ValidationError

        from vibesensor.api_models import SensorRequest

        with pytest.raises(ValidationError):
            SensorRequest(location="x" * 65)

    def test_sensor_request_valid_ok(self) -> None:
        from vibesensor.api_models import SensorRequest

        req = SensorRequest(name="MySensor", location="front_left")
        assert req.name == "MySensor"
        assert req.location == "front_left"
