"""Analysis settings drop invalid values and keep the previous ones."""

from __future__ import annotations

from math import inf, nan
from pathlib import Path

import pytest

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.history.history_db import HistoryDB
from vibesensor.settings.analysis_settings_schema import sanitize_analysis_settings
from vibesensor.settings.services import build_settings_services


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"tire_width_mm": -1.0, "rim_in": 0.0}, id="non-positive-required"),
        pytest.param({"speed_uncertainty_pct": -0.1}, id="negative-non-negative-field"),
        pytest.param({"unknown_field": 42.0}, id="unknown-key"),
        pytest.param({"tire_width_mm": nan, "rim_in": inf}, id="non-finite"),
    ],
)
def test_sanitize_drops_invalid_values(raw: dict[str, float]) -> None:
    assert sanitize_analysis_settings(raw) == {}


def test_update_rejects_invalid_and_keeps_old(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "test.db")
    services = build_settings_services(db=db)
    initial = services.car_settings.add_car({"name": "Test"})
    services.car_settings.set_active_car(initial.cars[0]["id"])
    services.analysis_settings.update_active_car_aspects({"tire_width_mm": -5.0})
    assert (
        services.analysis_settings.analysis_settings_snapshot().tire_width_mm
        == AnalysisSettingsSnapshot.DEFAULTS["tire_width_mm"]
    )
