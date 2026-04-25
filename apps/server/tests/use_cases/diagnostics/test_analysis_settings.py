from __future__ import annotations

from math import inf, nan, pi

import pytest

from vibesensor.domain import AxleTireSetup, OrderReferenceSpec, TireSpec
from vibesensor.domain import Car as _Car
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.analysis_settings_schema import sanitize_analysis_settings
from vibesensor.shared.order_reference_settings import order_reference_spec_from_mapping

DEFAULT_ANALYSIS_SETTINGS = AnalysisSettingsSnapshot.DEFAULTS
sanitize_settings = sanitize_analysis_settings

# -- TireSpec.circumference_m -------------------------------------------------


def _circ(w: float, a: float, r: float, df: float = 1.0) -> float | None:
    spec = TireSpec.from_aspects(
        {"tire_width_mm": w, "tire_aspect_pct": a, "rim_in": r},
        deflection_factor=df,
    )
    return spec.circumference_m if spec is not None else None


def test_tire_circumference_typical_spec() -> None:
    # 285/30R21 → sidewall 85.5 mm, diameter 704.4 mm (no deflection)
    result = _circ(285.0, 30.0, 21.0)
    assert result is not None
    expected_diameter_m = ((21.0 * 25.4) + (2.0 * 285.0 * 30.0 / 100.0)) / 1000.0
    assert abs(result - expected_diameter_m * pi) < 1e-9


def test_tire_circumference_with_deflection_factor() -> None:
    # Deflection factor of 0.97 reduces circumference by 3%.
    no_deflection = _circ(285.0, 30.0, 21.0)
    with_deflection = _circ(285.0, 30.0, 21.0, df=0.97)
    assert no_deflection is not None and with_deflection is not None
    assert abs(with_deflection - no_deflection * 0.97) < 1e-9


def test_tire_circumference_deflection_factor_one_is_identity() -> None:
    no_deflection = _circ(285.0, 30.0, 21.0)
    factor_one = _circ(285.0, 30.0, 21.0, df=1.0)
    assert no_deflection is not None and factor_one is not None
    assert abs(factor_one - no_deflection) < 1e-9


def test_tire_deflection_factor_in_default_analysis_settings() -> None:
    assert "tire_deflection_factor" in DEFAULT_ANALYSIS_SETTINGS
    assert DEFAULT_ANALYSIS_SETTINGS["tire_deflection_factor"] == 0.97


def test_tire_circumference_returns_none_for_none_inputs() -> None:
    assert TireSpec.from_aspects({"tire_aspect_pct": 30.0, "rim_in": 21.0}) is None
    assert TireSpec.from_aspects({"tire_width_mm": 285.0, "rim_in": 21.0}) is None
    assert TireSpec.from_aspects({"tire_width_mm": 285.0, "tire_aspect_pct": 30.0}) is None


_D = {"tire_width_mm": 285.0, "tire_aspect_pct": 30.0, "rim_in": 21.0}


def test_tire_circumference_returns_none_for_zero_or_negative() -> None:
    assert TireSpec.from_aspects({**_D, "tire_width_mm": 0}) is None
    assert TireSpec.from_aspects({**_D, "tire_aspect_pct": 0}) is None
    assert TireSpec.from_aspects({**_D, "rim_in": 0}) is None
    assert TireSpec.from_aspects({**_D, "tire_width_mm": -1}) is None


def test_tire_circumference_returns_none_for_non_finite_values() -> None:
    assert TireSpec.from_aspects({**_D, "tire_width_mm": nan}) is None
    assert TireSpec.from_aspects({**_D, "tire_aspect_pct": inf}) is None


def test_tire_circumference_deflection_factor_above_one_ignored() -> None:
    """Deflection factor > 1.0 is physically unrealistic and must be ignored."""
    no_deflection = _circ(285.0, 30.0, 21.0)
    above_one = _circ(285.0, 30.0, 21.0, df=1.5)
    assert no_deflection is not None and above_one is not None
    assert abs(above_one - no_deflection) < 1e-9  # factor ignored


def test_car_tire_circumference_happy_path() -> None:
    """Car.tire_circumference_m returns a plausible value for a complete 205/55 R16 spec."""
    car = _Car(
        name="Test",
        aspects={"tire_width_mm": 205, "tire_aspect_pct": 55, "rim_in": 16},
    )
    circ = car.tire_circumference_m
    assert circ is not None
    # 205/55 R16: diameter ≈ 632 mm → circumference ≈ 1.985 m
    assert 1.9 < circ < 2.1


def test_car_tire_circumference_no_aspects_returns_none() -> None:
    """Car.tire_circumference_m returns None when car has no tire aspects."""
    car = _Car(name="No Tires")
    assert car.tire_circumference_m is None


def test_wheel_hz_returns_none_for_non_finite_speed() -> None:
    spec = order_reference_spec_from_mapping(DEFAULT_ANALYSIS_SETTINGS)
    assert spec is not None
    assert spec.wheel_hz(nan) is None
    assert spec.wheel_hz(inf) is None


# -- sanitize_settings --------------------------------------------------------


def test_sanitize_rejects_negative_positive_required() -> None:
    result = sanitize_settings({"tire_width_mm": -1.0, "rim_in": 0.0})
    assert "tire_width_mm" not in result
    assert "rim_in" not in result


def test_sanitize_rejects_negative_non_negative_field() -> None:
    result = sanitize_settings({"speed_uncertainty_pct": -0.1})
    assert "speed_uncertainty_pct" not in result


def test_sanitize_allows_zero_for_non_negative() -> None:
    result = sanitize_settings({"speed_uncertainty_pct": 0.0})
    assert result["speed_uncertainty_pct"] == 0.0


def test_sanitize_ignores_unknown_keys() -> None:
    result = sanitize_settings({"unknown_field": 42.0})
    assert "unknown_field" not in result


def test_sanitize_converts_to_float() -> None:
    result = sanitize_settings({"tire_width_mm": 285})
    assert isinstance(result["tire_width_mm"], float)


def test_sanitize_rejects_non_finite_values() -> None:
    result = sanitize_settings({"tire_width_mm": nan, "rim_in": inf})
    assert "tire_width_mm" not in result
    assert "rim_in" not in result


# -- SettingsStore analysis settings snapshot / update ------------------------


def test_snapshot_returns_copy_of_defaults(tmp_path) -> None:
    from test_support.settings_services import build_settings_services

    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters

    db = create_history_persistence_adapters(tmp_path / "test.db")
    services = build_settings_services(db=db.settings_snapshot_repository)
    snap = services.analysis_settings.analysis_settings_snapshot()
    # Frozen dataclass — values match defaults and instance is immutable
    assert snap.tire_width_mm == DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"]
    assert snap.rim_in == DEFAULT_ANALYSIS_SETTINGS["rim_in"]


def test_update_merges_valid_values(tmp_path) -> None:
    from test_support.settings_services import build_settings_services

    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters

    db = create_history_persistence_adapters(tmp_path / "test.db")
    services = build_settings_services(db=db.settings_snapshot_repository)
    initial = services.car_settings.add_car({"name": "Test"})
    services.car_settings.set_active_car(initial.cars[0]["id"])
    services.analysis_settings.update_active_car_aspects({"tire_width_mm": 225.0})
    result = services.analysis_settings.analysis_settings_snapshot()
    assert result.tire_width_mm == 225.0
    assert result.rim_in == DEFAULT_ANALYSIS_SETTINGS["rim_in"]


def test_update_rejects_invalid_and_keeps_old(tmp_path) -> None:
    from test_support.settings_services import build_settings_services

    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters

    db = create_history_persistence_adapters(tmp_path / "test.db")
    services = build_settings_services(db=db.settings_snapshot_repository)
    initial = services.car_settings.add_car({"name": "Test"})
    services.car_settings.set_active_car(initial.cars[0]["id"])
    services.analysis_settings.update_active_car_aspects({"tire_width_mm": -5.0})
    assert (
        services.analysis_settings.analysis_settings_snapshot().tire_width_mm
        == DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"]
    )


def test_sanitize_clamps_absurd_values() -> None:
    out = sanitize_settings(
        {
            "wheel_bandwidth_pct": 99999,
            "speed_uncertainty_pct": 99999,
            "min_abs_band_hz": 99999,
        },
    )
    assert out["wheel_bandwidth_pct"] == 100.0
    assert out["speed_uncertainty_pct"] == 100.0
    assert out["min_abs_band_hz"] == 500.0


def test_sanitize_keeps_normal_values_unchanged() -> None:
    out = sanitize_settings({"wheel_bandwidth_pct": 6.0, "speed_uncertainty_pct": 0.6})
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
    field: str,
    raw_value: float,
    clamped_value: float,
) -> None:
    out = sanitize_settings({field: raw_value})
    assert out[field] == clamped_value


def test_sanitize_keeps_valid_tire_params_unchanged() -> None:
    out = sanitize_settings({"tire_width_mm": 225.0, "tire_aspect_pct": 45.0, "rim_in": 18.0})
    assert out["tire_width_mm"] == 225.0
    assert out["tire_aspect_pct"] == 45.0
    assert out["rim_in"] == 18.0


# -- OrderReferenceSpec.wheel_hz / engine_hz -----------------------------------


def _default_spec() -> OrderReferenceSpec:
    spec = order_reference_spec_from_mapping(DEFAULT_ANALYSIS_SETTINGS)
    assert spec is not None
    return spec


def test_wheel_hz_from_speed_kmh_typical_value() -> None:
    """100 km/h → wheel Hz consistent with tire circumference."""
    spec = _default_spec()
    result = spec.wheel_hz_from_speed_kmh(100.0)
    assert result is not None
    assert abs(result - (100.0 / 3.6 / spec.tire_circumference_m)) < 1e-9


@pytest.mark.parametrize(
    "speed",
    [0.0, -50.0, nan, inf],
    ids=["zero-speed", "negative-speed", "nan-speed", "inf-speed"],
)
def test_wheel_hz_from_speed_kmh_invalid_returns_none(speed: float) -> None:
    spec = _default_spec()
    assert spec.wheel_hz_from_speed_kmh(speed) is None


# -- OrderReferenceSpec.engine_rpm_from_wheel_hz -------------------------------


def test_engine_rpm_from_wheel_hz_basic() -> None:
    """10 Hz wheel × final_drive × gear × 60 = expected RPM."""
    spec = _default_spec()
    result = spec.engine_rpm_from_wheel_hz(10.0)
    assert result is not None
    assert abs(result - 10.0 * spec.final_drive_ratio * spec.current_gear_ratio * 60.0) < 1e-6


def test_engine_rpm_from_wheel_hz_non_finite_inputs_return_none() -> None:
    """Non-finite inputs must return None to avoid propagating nan/inf."""
    spec = _default_spec()
    assert spec.engine_rpm_from_wheel_hz(float("nan")) is None
    assert spec.engine_rpm_from_wheel_hz(float("inf")) is None


def test_engine_hz_returns_none_without_gear() -> None:
    """engine_hz returns None when gear ratio is zero."""
    tire = TireSpec(width_mm=285.0, aspect_pct=30.0, rim_in=21.0)
    spec = OrderReferenceSpec(
        tire_setup=AxleTireSetup.square(tire),
        final_drive_ratio=3.08,
        current_gear_ratio=0.0,
        wheel_bandwidth_pct=5.0,
        driveshaft_bandwidth_pct=4.5,
        engine_bandwidth_pct=5.2,
        speed_uncertainty_pct=1.0,
        tire_diameter_uncertainty_pct=1.0,
        final_drive_uncertainty_pct=0.1,
        gear_uncertainty_pct=0.2,
        min_abs_band_hz=0.2,
        max_band_half_width_pct=6.0,
    )
    assert spec.engine_hz(10.0) is None


def test_engine_rpm_from_wheel_hz_zero_wheel_hz_returns_zero() -> None:
    """Zero wheel Hz (stopped vehicle) must return 0.0, not None."""
    spec = _default_spec()
    result = spec.engine_rpm_from_wheel_hz(0.0)
    assert result == 0.0
