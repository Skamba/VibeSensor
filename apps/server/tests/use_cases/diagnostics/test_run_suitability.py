"""Direct behavior tests for run suitability evaluation."""

from __future__ import annotations

from typing import Any

import pytest

from vibesensor.domain import RunSuitability

_SUITABILITY_DEFAULTS: dict[str, Any] = {
    "steady_speed": False,
    "speed_sufficient": True,
    "sensor_count": 3,
    "reference_complete": True,
    "sat_count": 0,
    "total_dropped": 0,
    "total_overflow": 0,
}


def _suitability_checks(**overrides: Any) -> list[dict[str, Any]]:
    kw = {**_SUITABILITY_DEFAULTS, **overrides}
    return [
        {"check_key": check.check_key, "state": check.state}
        for check in RunSuitability.evaluate(**kw).checks
    ]


class TestBuildRunSuitabilityChecks:
    """Direct unit tests for run suitability checks."""

    def test_all_pass(self) -> None:
        checks = _suitability_checks()
        assert all(c["state"] == "pass" for c in checks), (
            f"All checks should pass: {[c['check_key'] for c in checks if c['state'] != 'pass']}"
        )

    @pytest.mark.parametrize(
        ("overrides", "check_key"),
        [
            pytest.param(
                {"sensor_count": 1},
                "SUITABILITY_CHECK_SENSOR_COVERAGE",
                id="sensor_coverage_below_3",
            ),
            pytest.param(
                {"sat_count": 5},
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                id="saturation",
            ),
            pytest.param(
                {"total_dropped": 10},
                "SUITABILITY_CHECK_FRAME_INTEGRITY",
                id="frame_integrity_dropped",
            ),
            pytest.param(
                {"reference_complete": False},
                "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                id="reference_incomplete",
            ),
        ],
    )
    def test_warn_condition(self, overrides: dict[str, Any], check_key: str) -> None:
        checks = _suitability_checks(**overrides)
        check = next(c for c in checks if c["check_key"] == check_key)
        assert check["state"] == "warn"

    def test_steady_speed_marks_speed_variation_as_pass(self) -> None:
        checks = _suitability_checks(steady_speed=True)
        check = next(c for c in checks if c["check_key"] == "SUITABILITY_CHECK_SPEED_VARIATION")
        assert check["state"] == "pass"
