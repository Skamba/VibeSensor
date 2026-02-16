from __future__ import annotations

from math import pi

from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettingsStore,
    tire_circumference_m_from_spec,
)

# -- tire_circumference_m_from_spec -------------------------------------------


def test_tire_circumference_typical_spec() -> None:
    # 285/30R21 → sidewall 85.5 mm, diameter 618.4 mm
    result = tire_circumference_m_from_spec(285.0, 30.0, 21.0)
    assert result is not None
    expected_diameter_m = ((21.0 * 25.4) + (2.0 * 285.0 * 30.0 / 100.0)) / 1000.0
    assert abs(result - expected_diameter_m * pi) < 1e-9


def test_tire_circumference_returns_none_for_none_inputs() -> None:
    assert tire_circumference_m_from_spec(None, 30.0, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, None, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, 30.0, None) is None


def test_tire_circumference_returns_none_for_zero_or_negative() -> None:
    assert tire_circumference_m_from_spec(0, 30.0, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, 0, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, 30.0, 0) is None
    assert tire_circumference_m_from_spec(-1, 30.0, 21.0) is None


# -- AnalysisSettingsStore._sanitize ------------------------------------------


def test_sanitize_rejects_negative_positive_required() -> None:
    store = AnalysisSettingsStore()
    result = store._sanitize({"tire_width_mm": -1.0, "rim_in": 0.0})
    assert "tire_width_mm" not in result
    assert "rim_in" not in result


def test_sanitize_rejects_negative_non_negative_field() -> None:
    store = AnalysisSettingsStore()
    result = store._sanitize({"speed_uncertainty_pct": -0.1})
    assert "speed_uncertainty_pct" not in result


def test_sanitize_allows_zero_for_non_negative() -> None:
    store = AnalysisSettingsStore()
    result = store._sanitize({"speed_uncertainty_pct": 0.0})
    assert result["speed_uncertainty_pct"] == 0.0


def test_sanitize_ignores_unknown_keys() -> None:
    store = AnalysisSettingsStore()
    result = store._sanitize({"unknown_field": 42.0})
    assert "unknown_field" not in result


def test_sanitize_converts_to_float() -> None:
    store = AnalysisSettingsStore()
    result = store._sanitize({"tire_width_mm": 285})
    assert isinstance(result["tire_width_mm"], float)


# -- AnalysisSettingsStore snapshot / update ----------------------------------


def test_snapshot_returns_copy_of_defaults() -> None:
    store = AnalysisSettingsStore()
    snap = store.snapshot()
    assert snap == DEFAULT_ANALYSIS_SETTINGS
    snap["tire_width_mm"] = 999.0
    assert store.snapshot()["tire_width_mm"] == DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"]


def test_update_merges_valid_values() -> None:
    store = AnalysisSettingsStore()
    result = store.update({"tire_width_mm": 225.0})
    assert result["tire_width_mm"] == 225.0
    assert result["rim_in"] == DEFAULT_ANALYSIS_SETTINGS["rim_in"]


def test_update_rejects_invalid_and_keeps_old() -> None:
    store = AnalysisSettingsStore()
    store.update({"tire_width_mm": -5.0})
    assert store.snapshot()["tire_width_mm"] == DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"]
