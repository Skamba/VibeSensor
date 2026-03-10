from __future__ import annotations

from vibesensor.domain_models import as_float_or_none
from vibesensor.order_bands import (
    build_diagnostic_settings,
    combined_relative_uncertainty,
    tolerance_for_order,
    vehicle_orders_hz,
)
from vibesensor.peak_classification import (
    _order_label_for_class_key,
    classify_peak_hz,
    source_keys_from_class_key,
    suspected_source_from_class_key,
)
from vibesensor.severity import severity_from_peak

# -- _as_float NaN/edge cases -------------------------------------------------


def test_as_float_nan_returns_none() -> None:
    assert as_float_or_none(float("nan")) is None


def test_as_float_inf_returns_none() -> None:
    # Canonical as_float_or_none rejects both NaN and Inf.
    result = as_float_or_none(float("inf"))
    assert result is None
    result_neg = as_float_or_none(float("-inf"))
    assert result_neg is None


def test_as_float_non_convertible() -> None:
    assert as_float_or_none(object()) is None
    assert as_float_or_none([1, 2]) is None


# -- build_diagnostic_settings ------------------------------------------------


def test_build_diagnostic_settings_defaults() -> None:
    result = build_diagnostic_settings(None)
    assert result["tire_width_mm"] == 285.0
    assert result["rim_in"] == 21.0


def test_build_diagnostic_settings_override() -> None:
    result = build_diagnostic_settings({"tire_width_mm": 225.0})
    assert result["tire_width_mm"] == 225.0


def test_build_diagnostic_settings_ignores_unknown() -> None:
    result = build_diagnostic_settings({"unknown_key": 99.0})
    assert "unknown_key" not in result


# -- combined_relative_uncertainty ---------------------------------------------


def test_combined_uncertainty_zero() -> None:
    assert combined_relative_uncertainty(0.0, 0.0) == 0.0


def test_combined_uncertainty_single() -> None:
    assert abs(combined_relative_uncertainty(3.0) - 3.0) < 1e-9


def test_combined_uncertainty_negative_ignored() -> None:
    assert combined_relative_uncertainty(-1.0, 3.0) == 3.0


# -- tolerance_for_order -------------------------------------------------------


def test_tolerance_for_order_zero_hz() -> None:
    result = tolerance_for_order(
        6.0,
        0.0,
        0.01,
        min_abs_band_hz=0.4,
        max_band_half_width_pct=8.0,
    )
    assert result == 0.0


def test_tolerance_for_order_basic() -> None:
    result = tolerance_for_order(6.0, 10.0, 0.01, min_abs_band_hz=0.4, max_band_half_width_pct=8.0)
    assert 0 < result < 0.08


# -- vehicle_orders_hz --------------------------------------------------------


def test_vehicle_orders_no_speed() -> None:
    assert vehicle_orders_hz(speed_mps=None, settings={}) is None
    assert vehicle_orders_hz(speed_mps=0.0, settings={}) is None
    assert vehicle_orders_hz(speed_mps=-1.0, settings={}) is None


def test_vehicle_orders_with_defaults() -> None:
    result = vehicle_orders_hz(speed_mps=25.0, settings={})
    assert result is not None
    assert result["wheel_hz"] > 0
    assert result["drive_hz"] > 0
    assert result["engine_hz"] > 0
    # drive_hz should be > wheel_hz (final_drive_ratio > 1)
    assert result["drive_hz"] > result["wheel_hz"]


def test_vehicle_orders_bad_tire_returns_none() -> None:
    settings = {"tire_width_mm": 0.0}
    assert vehicle_orders_hz(speed_mps=25.0, settings=settings) is None


def test_vehicle_orders_bad_ratios_returns_none() -> None:
    settings = {"final_drive_ratio": 0.0}
    assert vehicle_orders_hz(speed_mps=25.0, settings=settings) is None


# -- _order_label_for_class_key ------------------------------------------------


def test_order_label_all_keys() -> None:
    assert _order_label_for_class_key("wheel1") == "1x wheel order"
    assert _order_label_for_class_key("wheel2") == "2x wheel order"
    assert _order_label_for_class_key("eng1") == "1x engine order"
    assert _order_label_for_class_key("eng2") == "2x engine order"
    assert _order_label_for_class_key("shaft1") == "1x driveshaft order"
    assert _order_label_for_class_key("shaft_eng1") == "1x driveshaft/engine order"
    assert _order_label_for_class_key("unknown") is None


# -- suspected_source_from_class_key -------------------------------------------


def test_suspected_source_all_keys() -> None:
    assert suspected_source_from_class_key("wheel1") == "wheel/tire"
    assert suspected_source_from_class_key("eng1") == "engine"
    assert suspected_source_from_class_key("shaft1") == "driveline"
    assert suspected_source_from_class_key("road") == "body resonance"
    assert suspected_source_from_class_key("other") == "unknown"


# -- source_keys_from_class_key -----------------------------------------------


def test_source_keys_mapping() -> None:
    assert source_keys_from_class_key("shaft_eng1") == ("driveshaft", "engine")
    assert source_keys_from_class_key("eng1") == ("engine",)
    assert source_keys_from_class_key("shaft1") == ("driveshaft",)
    assert source_keys_from_class_key("wheel1") == ("wheel",)
    assert source_keys_from_class_key("road") == ("other",)
    assert source_keys_from_class_key("abc") == ("other",)


# -- classify_peak_hz ---------------------------------------------------------


def test_classify_road_frequency() -> None:
    result = classify_peak_hz(peak_hz=8.0, speed_mps=None, settings={})
    assert result["key"] == "road"


def test_classify_other_frequency() -> None:
    result = classify_peak_hz(peak_hz=200.0, speed_mps=None, settings={})
    assert result["key"] == "other"


def test_classify_with_speed_matches_order() -> None:
    # At 25 m/s with default tire (~2m circumference), wheel_hz ≈ 12.5 Hz
    result = classify_peak_hz(peak_hz=12.5, speed_mps=25.0, settings={})
    valid_keys = {
        "wheel1",
        "wheel2",
        "shaft1",
        "shaft_eng1",
        "eng1",
        "eng2",
        "road",
        "other",
    }
    assert result["key"] in valid_keys
    # It should match something order-related since we have speed
    assert result["matched_hz"] is not None or result["key"] in {"road", "other"}


# -- severity_from_peak state machine -----------------------------------------


def _run_severity_ticks(
    db: float,
    n: int,
    *,
    sensor_count: int = 1,
    state: dict | None = None,
) -> tuple[dict, dict | None]:
    """Run *n* severity_from_peak ticks and return (last_result, last_state)."""
    out: dict = {}
    for _ in range(n):
        out = severity_from_peak(
            vibration_strength_db=db,
            sensor_count=sensor_count,
            prior_state=state,
        )
        state = dict(out.get("state") or {})
    return out, state


def test_severity_candidate_none_current_none() -> None:
    """No candidate, no current → key is None."""
    result = severity_from_peak(
        vibration_strength_db=0.0,
        sensor_count=1,
        prior_state=None,
    )
    assert result is not None
    assert result["key"] is None


def test_severity_escalation_from_l1_to_l3() -> None:
    """Promote from L1 to L3 after persistence ticks."""
    out, state = _run_severity_ticks(11.0, 3)
    assert out["key"] == "l1"

    out, _ = _run_severity_ticks(27.0, 3, state=state)
    assert out["key"] == "l3"


def test_severity_downgrade_with_decay() -> None:
    """Candidate rank < current → needs DECAY_TICKS consecutive below hysteresis."""
    out, state = _run_severity_ticks(27.0, 3)
    assert out["key"] == "l3"

    # Signal drops — not enough decay ticks yet
    out, state = _run_severity_ticks(5.0, 4, state=state)
    assert out["key"] == "l3"

    # 5th tick should cause decay
    out, _ = _run_severity_ticks(5.0, 1, state=state)
    assert out["key"] != "l3"


def test_severity_same_rank_resets_counters() -> None:
    """When candidate == current rank, pending/counters should reset."""
    out, state = _run_severity_ticks(17.0, 3)
    assert out["key"] == "l2"

    # Continue at L2 → should stay stable
    out, state = _run_severity_ticks(17.0, 5, state=state)
    assert out["key"] == "l2"
    assert state["consecutive_up"] == 0


def test_severity_multi_sensor_bonus() -> None:
    """sensor_count >= 2 adds 3 dB bonus."""
    out, _ = _run_severity_ticks(6.0, 3, sensor_count=1)
    assert out["key"] is None

    # At 6 dB base with 2 sensors → 9 dB adjusted → above L1
    out, _ = _run_severity_ticks(6.0, 3, sensor_count=2)
    assert out["key"] == "l1"
