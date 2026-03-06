from __future__ import annotations

from math import inf, nan, pi

import pytest

from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettingsStore,
    engine_rpm_from_wheel_hz,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
    wheel_hz_from_speed_mps,
)


@pytest.fixture
def store() -> AnalysisSettingsStore:
    return AnalysisSettingsStore()


# -- tire_circumference_m_from_spec -------------------------------------------


def test_tire_circumference_typical_spec() -> None:
    # 285/30R21 → sidewall 85.5 mm, diameter 704.4 mm (no deflection)
    result = tire_circumference_m_from_spec(285.0, 30.0, 21.0, deflection_factor=None)
    assert result is not None
    expected_diameter_m = ((21.0 * 25.4) + (2.0 * 285.0 * 30.0 / 100.0)) / 1000.0
    assert abs(result - expected_diameter_m * pi) < 1e-9


def test_tire_circumference_with_deflection_factor() -> None:
    # Deflection factor of 0.97 reduces circumference by 3%.
    no_deflection = tire_circumference_m_from_spec(285.0, 30.0, 21.0, deflection_factor=None)
    with_deflection = tire_circumference_m_from_spec(285.0, 30.0, 21.0, deflection_factor=0.97)
    assert no_deflection is not None and with_deflection is not None
    assert abs(with_deflection - no_deflection * 0.97) < 1e-9


def test_tire_circumference_deflection_factor_one_is_identity() -> None:
    no_deflection = tire_circumference_m_from_spec(285.0, 30.0, 21.0, deflection_factor=None)
    factor_one = tire_circumference_m_from_spec(285.0, 30.0, 21.0, deflection_factor=1.0)
    assert no_deflection is not None and factor_one is not None
    assert abs(factor_one - no_deflection) < 1e-9


def test_tire_circumference_deflection_factor_none_omitted() -> None:
    # When deflection_factor is None, no deflection applied.
    a = tire_circumference_m_from_spec(285.0, 30.0, 21.0)
    b = tire_circumference_m_from_spec(285.0, 30.0, 21.0, deflection_factor=None)
    assert a is not None and b is not None
    assert a == b


def test_tire_deflection_factor_in_default_analysis_settings() -> None:
    assert "tire_deflection_factor" in DEFAULT_ANALYSIS_SETTINGS
    assert DEFAULT_ANALYSIS_SETTINGS["tire_deflection_factor"] == 0.97


def test_tire_circumference_returns_none_for_none_inputs() -> None:
    assert tire_circumference_m_from_spec(None, 30.0, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, None, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, 30.0, None) is None


def test_tire_circumference_returns_none_for_zero_or_negative() -> None:
    assert tire_circumference_m_from_spec(0, 30.0, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, 0, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, 30.0, 0) is None
    assert tire_circumference_m_from_spec(-1, 30.0, 21.0) is None


def test_tire_circumference_returns_none_for_non_finite_values() -> None:
    assert tire_circumference_m_from_spec(nan, 30.0, 21.0) is None
    assert tire_circumference_m_from_spec(285.0, inf, 21.0) is None


def test_tire_circumference_deflection_factor_above_one_ignored() -> None:
    """Deflection factor > 1.0 is physically unrealistic and must be ignored."""
    no_deflection = tire_circumference_m_from_spec(285.0, 30.0, 21.0, deflection_factor=None)
    above_one = tire_circumference_m_from_spec(285.0, 30.0, 21.0, deflection_factor=1.5)
    assert no_deflection is not None and above_one is not None
    assert abs(above_one - no_deflection) < 1e-9  # factor ignored


def test_wheel_hz_from_speed_mps_returns_none_for_non_finite_values() -> None:
    assert wheel_hz_from_speed_mps(nan, 2.0) is None
    assert wheel_hz_from_speed_mps(20.0, inf) is None


# -- AnalysisSettingsStore._sanitize ------------------------------------------


def test_sanitize_rejects_negative_positive_required(store: AnalysisSettingsStore) -> None:
    result = store._sanitize({"tire_width_mm": -1.0, "rim_in": 0.0})
    assert "tire_width_mm" not in result
    assert "rim_in" not in result


def test_sanitize_rejects_negative_non_negative_field(store: AnalysisSettingsStore) -> None:
    result = store._sanitize({"speed_uncertainty_pct": -0.1})
    assert "speed_uncertainty_pct" not in result


def test_sanitize_allows_zero_for_non_negative(store: AnalysisSettingsStore) -> None:
    result = store._sanitize({"speed_uncertainty_pct": 0.0})
    assert result["speed_uncertainty_pct"] == 0.0


def test_sanitize_ignores_unknown_keys(store: AnalysisSettingsStore) -> None:
    result = store._sanitize({"unknown_field": 42.0})
    assert "unknown_field" not in result


def test_sanitize_converts_to_float(store: AnalysisSettingsStore) -> None:
    result = store._sanitize({"tire_width_mm": 285})
    assert isinstance(result["tire_width_mm"], float)


def test_sanitize_rejects_non_finite_values(store: AnalysisSettingsStore) -> None:
    result = store._sanitize({"tire_width_mm": nan, "rim_in": inf})
    assert "tire_width_mm" not in result
    assert "rim_in" not in result


# -- AnalysisSettingsStore snapshot / update ----------------------------------


def test_snapshot_returns_copy_of_defaults(store: AnalysisSettingsStore) -> None:
    snap = store.snapshot()
    assert snap == DEFAULT_ANALYSIS_SETTINGS
    snap["tire_width_mm"] = 999.0
    assert store.snapshot()["tire_width_mm"] == DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"]


def test_update_merges_valid_values(store: AnalysisSettingsStore) -> None:
    result = store.update({"tire_width_mm": 225.0})
    assert result["tire_width_mm"] == 225.0
    assert result["rim_in"] == DEFAULT_ANALYSIS_SETTINGS["rim_in"]


def test_update_rejects_invalid_and_keeps_old(store: AnalysisSettingsStore) -> None:
    store.update({"tire_width_mm": -5.0})
    assert store.snapshot()["tire_width_mm"] == DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"]


def test_sanitize_clamps_absurd_values(store: AnalysisSettingsStore) -> None:
    out = store._sanitize(
        {
            "wheel_bandwidth_pct": 99999,
            "speed_uncertainty_pct": 99999,
            "min_abs_band_hz": 99999,
        }
    )
    assert out["wheel_bandwidth_pct"] == 100.0
    assert out["speed_uncertainty_pct"] == 100.0
    assert out["min_abs_band_hz"] == 500.0


def test_sanitize_keeps_normal_values_unchanged(store: AnalysisSettingsStore) -> None:
    out = store._sanitize({"wheel_bandwidth_pct": 6.0, "speed_uncertainty_pct": 0.6})
    assert out["wheel_bandwidth_pct"] == 6.0
    assert out["speed_uncertainty_pct"] == 0.6


# -- Tire/rim upper-bound clamping (#288) ------------------------------------


@pytest.mark.parametrize(
    ("field", "raw_value", "clamped_value"),
    [
        ("tire_width_mm", 999999.0, 500.0),
        ("tire_width_mm", 50.0, 100.0),
        ("tire_aspect_pct", 200.0, 90.0),
        ("tire_aspect_pct", 5.0, 10.0),
        ("rim_in", 1000.0, 30.0),
        ("rim_in", 5.0, 10.0),
    ],
    ids=[
        "tire_width-upper",
        "tire_width-lower",
        "tire_aspect-upper",
        "tire_aspect-lower",
        "rim-upper",
        "rim-lower",
    ],
)
def test_sanitize_clamps_out_of_range(
    store: AnalysisSettingsStore, field: str, raw_value: float, clamped_value: float
) -> None:
    out = store._sanitize({field: raw_value})
    assert out[field] == clamped_value


def test_sanitize_keeps_valid_tire_params_unchanged(store: AnalysisSettingsStore) -> None:
    out = store._sanitize({"tire_width_mm": 225.0, "tire_aspect_pct": 45.0, "rim_in": 18.0})
    assert out["tire_width_mm"] == 225.0
    assert out["tire_aspect_pct"] == 45.0
    assert out["rim_in"] == 18.0


# -- wheel_hz_from_speed_kmh --------------------------------------------------


def test_wheel_hz_from_speed_kmh_typical_value() -> None:
    """100 km/h with 2m circumference → ~13.9 Hz."""
    result = wheel_hz_from_speed_kmh(100.0, 2.0)
    assert result is not None
    assert abs(result - (100.0 / 3.6 / 2.0)) < 1e-9


@pytest.mark.parametrize(
    ("speed", "circ"),
    [
        (0.0, 2.0),
        (-50.0, 2.0),
        (100.0, 0.0),
        (nan, 2.0),
        (100.0, inf),
        (inf, 2.0),
    ],
    ids=["zero-speed", "negative-speed", "zero-circ", "nan-speed", "inf-circ", "inf-speed"],
)
def test_wheel_hz_from_speed_kmh_invalid_returns_none(speed: float, circ: float) -> None:
    assert wheel_hz_from_speed_kmh(speed, circ) is None


# -- engine_rpm_from_wheel_hz -------------------------------------------------


def test_engine_rpm_from_wheel_hz_basic() -> None:
    """10 Hz wheel × 3.08 final × 0.64 gear × 60 = 1182.72 RPM."""
    result = engine_rpm_from_wheel_hz(10.0, 3.08, 0.64)
    assert result is not None
    assert abs(result - 10.0 * 3.08 * 0.64 * 60.0) < 1e-6


def test_engine_rpm_from_wheel_hz_non_finite_inputs_return_none() -> None:
    """Non-finite inputs must return None to avoid propagating nan/inf."""
    assert engine_rpm_from_wheel_hz(float("nan"), 3.08, 0.64) is None
    assert engine_rpm_from_wheel_hz(float("inf"), 3.08, 0.64) is None
    assert engine_rpm_from_wheel_hz(10.0, float("nan"), 0.64) is None
    assert engine_rpm_from_wheel_hz(10.0, 3.08, float("inf")) is None


def test_engine_rpm_from_wheel_hz_non_positive_ratios_return_none() -> None:
    """Zero or negative drive ratios must return None (invalid configuration)."""
    assert engine_rpm_from_wheel_hz(10.0, 0.0, 0.64) is None
    assert engine_rpm_from_wheel_hz(10.0, -1.0, 0.64) is None
    assert engine_rpm_from_wheel_hz(10.0, 3.08, 0.0) is None
    assert engine_rpm_from_wheel_hz(10.0, 3.08, -0.5) is None


def test_engine_rpm_from_wheel_hz_zero_wheel_hz_returns_zero() -> None:
    """Zero wheel Hz (stopped vehicle) must return 0.0, not None."""
    result = engine_rpm_from_wheel_hz(0.0, 3.08, 0.64)
    assert result == 0.0
