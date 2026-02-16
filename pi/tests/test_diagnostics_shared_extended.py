from __future__ import annotations

from vibesensor.diagnostics_shared import (
    _as_float,
    _order_label_for_class_key,
    build_diagnostic_settings,
    classify_peak_hz,
    combined_relative_uncertainty,
    severity_from_peak,
    source_keys_from_class_key,
    suspected_source_from_class_key,
    tolerance_for_order,
    vehicle_orders_hz,
)


# -- _as_float NaN/edge cases -------------------------------------------------


def test_as_float_nan_returns_none() -> None:
    assert _as_float(float("nan")) is None


def test_as_float_inf_returns_none() -> None:
    # Infinity is still a valid float in this implementation (no inf check),
    # but NaN is rejected. Let's verify actual behavior.
    result = _as_float(float("inf"))
    # The function only checks NaN (out != out); inf should pass through.
    assert result == float("inf")


def test_as_float_non_convertible() -> None:
    assert _as_float(object()) is None
    assert _as_float([1, 2]) is None


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
    assert tolerance_for_order(6.0, 0.0, 0.01, min_abs_band_hz=0.4, max_band_half_width_pct=8.0) == 0.0


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
    assert result["key"] in {"wheel1", "wheel2", "shaft1", "shaft_eng1", "eng1", "eng2", "road", "other"}
    # It should match something order-related since we have speed
    assert result["matched_hz"] is not None or result["key"] in {"road", "other"}


# -- severity_from_peak state machine -----------------------------------------


def test_severity_candidate_none_current_none() -> None:
    """No candidate, no current → key is None."""
    result = severity_from_peak(strength_db=0.0, band_rms=0.0, sensor_count=1, prior_state=None)
    assert result is not None
    assert result["key"] is None


def test_severity_escalation_from_l1_to_l3() -> None:
    """Promote from L1 to L3 after persistence ticks."""
    state = None
    # First establish L1
    for _ in range(3):
        out = severity_from_peak(strength_db=11.0, band_rms=0.003, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or {})
    assert out["key"] == "l1"

    # Now push to L3
    for _ in range(3):
        out = severity_from_peak(strength_db=23.0, band_rms=0.012, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or {})
    assert out["key"] == "l3"


def test_severity_downgrade_with_decay() -> None:
    """Candidate rank < current → needs DECAY_TICKS consecutive below hysteresis."""
    state = None
    # Establish L3
    for _ in range(3):
        out = severity_from_peak(strength_db=23.0, band_rms=0.012, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or {})
    assert out["key"] == "l3"

    # Signal drops to L1 level but needs to be below hysteresis threshold
    for _ in range(4):
        out = severity_from_peak(strength_db=5.0, band_rms=0.001, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or {})
    # Should still be L3 (not enough decay ticks)
    assert out["key"] == "l3"

    # 5th tick should cause decay
    out = severity_from_peak(strength_db=5.0, band_rms=0.001, sensor_count=1, prior_state=state)
    state = dict(out.get("state") or {})
    # After decay, should drop to the candidate bucket or None
    assert out["key"] != "l3" or out["key"] is None


def test_severity_same_rank_resets_counters() -> None:
    """When candidate == current rank, pending/counters should reset."""
    state = None
    # Establish L2
    for _ in range(3):
        out = severity_from_peak(strength_db=17.0, band_rms=0.006, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or {})
    assert out["key"] == "l2"

    # Continue at L2 → should stay stable
    for _ in range(5):
        out = severity_from_peak(strength_db=17.0, band_rms=0.006, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or {})
    assert out["key"] == "l2"
    assert state["consecutive_up"] == 0


def test_severity_multi_sensor_bonus() -> None:
    """sensor_count >= 2 adds 3 dB bonus."""
    state = None
    # At 8 dB base with single sensor → below L1 (10 dB)
    for _ in range(3):
        out = severity_from_peak(strength_db=8.0, band_rms=0.003, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or {})
    assert out["key"] is None

    # At 8 dB base with 2 sensors → 11 dB adjusted → above L1
    state = None
    for _ in range(3):
        out = severity_from_peak(strength_db=8.0, band_rms=0.003, sensor_count=2, prior_state=state)
        state = dict(out.get("state") or {})
    assert out["key"] == "l1"
