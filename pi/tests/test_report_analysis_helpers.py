from __future__ import annotations

from vibesensor.report_analysis import (
    _as_float,
    _corr_abs,
    _effective_engine_rpm,
    _format_duration,
    _location_label,
    _mean_variance,
    _normalize_lang,
    _outlier_summary,
    _percent_missing,
    _percentile,
    _primary_vibration_amp,
    _sample_top_peaks,
    _sensor_limit_g,
    _speed_bin_label,
    _speed_bin_sort_key,
    _speed_stats,
    _text,
    _wheel_hz,
)

# -- _normalize_lang -----------------------------------------------------------


def test_normalize_lang_en_default() -> None:
    assert _normalize_lang("en") == "en"
    assert _normalize_lang("EN") == "en"
    assert _normalize_lang("") == "en"
    assert _normalize_lang(None) == "en"
    assert _normalize_lang(42) == "en"


def test_normalize_lang_nl() -> None:
    assert _normalize_lang("nl") == "nl"
    assert _normalize_lang("NL") == "nl"
    assert _normalize_lang("nl-NL") == "nl"


# -- _as_float -----------------------------------------------------------------


def test_as_float_valid() -> None:
    assert _as_float(3.14) == 3.14
    assert _as_float(0) == 0.0
    assert _as_float("2.5") == 2.5


def test_as_float_invalid() -> None:
    assert _as_float(None) is None
    assert _as_float("") is None
    assert _as_float("abc") is None
    assert _as_float(float("nan")) is None


# -- _format_duration ----------------------------------------------------------


def test_format_duration_zero() -> None:
    assert _format_duration(0) == "00:00.0"


def test_format_duration_90_seconds() -> None:
    assert _format_duration(90.0) == "01:30.0"


def test_format_duration_negative_clamped_to_zero() -> None:
    assert _format_duration(-5.0) == "00:00.0"


def test_format_duration_fractional() -> None:
    result = _format_duration(65.3)
    assert result == "01:05.3"


# -- _text (bilingual helper) -------------------------------------------------


def test_text_en() -> None:
    assert _text("en", "hello", "hallo") == "hello"


def test_text_nl() -> None:
    assert _text("nl", "hello", "hallo") == "hallo"


# -- _percent_missing ----------------------------------------------------------


def test_percent_missing_all_present() -> None:
    samples = [{"speed_kmh": 80}, {"speed_kmh": 90}]
    assert _percent_missing(samples, "speed_kmh") == 0.0


def test_percent_missing_some_missing() -> None:
    samples = [{"speed_kmh": 80}, {"speed_kmh": None}, {}, {"speed_kmh": ""}]
    assert abs(_percent_missing(samples, "speed_kmh") - 75.0) < 0.1


def test_percent_missing_empty_list() -> None:
    assert _percent_missing([], "speed_kmh") == 100.0


# -- _mean_variance ------------------------------------------------------------


def test_mean_variance_basic() -> None:
    m, v = _mean_variance([2.0, 4.0, 6.0])
    assert m is not None
    assert abs(m - 4.0) < 1e-9
    assert v is not None
    # var = ((2-4)^2 + (4-4)^2 + (6-4)^2) / 3 = 8/3
    assert abs(v - 8.0 / 3.0) < 1e-9


def test_mean_variance_empty() -> None:
    m, v = _mean_variance([])
    assert m is None
    assert v is None


# -- _percentile ---------------------------------------------------------------


def test_percentile_median() -> None:
    sorted_vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert abs(_percentile(sorted_vals, 0.5) - 3.0) < 1e-9


def test_percentile_empty_returns_zero() -> None:
    assert _percentile([], 0.5) == 0.0


def test_percentile_single_element() -> None:
    assert _percentile([7.0], 0.5) == 7.0


def test_percentile_boundary_values() -> None:
    sorted_vals = [10.0, 20.0, 30.0]
    assert abs(_percentile(sorted_vals, 0.0) - 10.0) < 1e-9
    assert abs(_percentile(sorted_vals, 1.0) - 30.0) < 1e-9


# -- _outlier_summary ----------------------------------------------------------


def test_outlier_summary_empty() -> None:
    result = _outlier_summary([])
    assert result["count"] == 0
    assert result["outlier_count"] == 0


def test_outlier_summary_no_outliers() -> None:
    values = [10.0, 11.0, 12.0, 11.5, 10.5]
    result = _outlier_summary(values)
    assert result["count"] == 5
    assert result["outlier_count"] == 0


def test_outlier_summary_with_outlier() -> None:
    values = [10.0, 10.0, 10.0, 10.0, 10.0, 100.0]
    result = _outlier_summary(values)
    assert result["outlier_count"] >= 1


# -- _speed_bin_label / _speed_bin_sort_key ------------------------------------


def test_speed_bin_label() -> None:
    assert _speed_bin_label(85.0) == "80-90 km/h"
    assert _speed_bin_label(100.0) == "100-110 km/h"
    assert _speed_bin_label(0.5) == "0-10 km/h"


def test_speed_bin_sort_key() -> None:
    assert _speed_bin_sort_key("80-90 km/h") == 80
    assert _speed_bin_sort_key("0-10 km/h") == 0
    assert _speed_bin_sort_key("invalid") == 0


# -- _speed_stats --------------------------------------------------------------


def test_speed_stats_empty() -> None:
    result = _speed_stats([])
    assert result["min_kmh"] is None
    assert result["steady_speed"] is True


def test_speed_stats_steady() -> None:
    values = [80.0, 80.5, 81.0, 80.2]
    result = _speed_stats(values)
    assert result["steady_speed"] is True
    assert result["min_kmh"] == 80.0
    assert result["max_kmh"] == 81.0


def test_speed_stats_not_steady() -> None:
    values = [30.0, 60.0, 90.0, 120.0]
    result = _speed_stats(values)
    assert result["steady_speed"] is False


# -- _sensor_limit_g -----------------------------------------------------------


def test_sensor_limit_adxl345() -> None:
    assert _sensor_limit_g("ADXL345") == 16.0
    assert _sensor_limit_g("my-adxl345-board") == 16.0


def test_sensor_limit_unknown() -> None:
    assert _sensor_limit_g("LIS3DH") is None
    assert _sensor_limit_g(None) is None
    assert _sensor_limit_g(42) is None


# -- _primary_vibration_amp ----------------------------------------------------


def test_primary_vibration_amp_prefers_vib_mag_rms() -> None:
    sample = {"vib_mag_rms_g": 0.05}
    assert _primary_vibration_amp(sample) == 0.05


def test_primary_vibration_amp_returns_none_for_missing() -> None:
    assert _primary_vibration_amp({}) is None
    # Legacy field names are no longer supported.
    assert _primary_vibration_amp({"accel_magnitude_rms_g": 0.04}) is None


# -- _sample_top_peaks ---------------------------------------------------------


def test_sample_top_peaks_from_top_peaks_field() -> None:
    sample = {"top_peaks": [{"hz": 15.0, "amp": 0.1}, {"hz": 30.0, "amp": 0.2}]}
    peaks = _sample_top_peaks(sample)
    assert len(peaks) == 2
    assert peaks[0] == (15.0, 0.1)


def test_sample_top_peaks_falls_back_to_dominant() -> None:
    sample = {"dominant_freq_hz": 25.0, "strength_peak_band_rms_amp_g": 0.15}
    peaks = _sample_top_peaks(sample)
    assert len(peaks) == 1
    assert peaks[0] == (25.0, 0.15)


def test_sample_top_peaks_filters_invalid() -> None:
    sample = {"top_peaks": [{"hz": -1.0, "amp": 0.1}, {"hz": 10.0, "amp": None}]}
    peaks = _sample_top_peaks(sample)
    assert len(peaks) == 0


# -- _location_label -----------------------------------------------------------


def test_location_label_with_name() -> None:
    assert _location_label({"client_name": "Front Left"}) == "Front Left"


def test_location_label_with_client_id_only() -> None:
    result = _location_label({"client_id": "AB:CD:EF:12:34:56"})
    assert result == "Sensor 4:56"


def test_location_label_unlabeled() -> None:
    assert _location_label({}) == "Unlabeled sensor"


# -- _wheel_hz -----------------------------------------------------------------


def test_wheel_hz_basic() -> None:
    sample = {"speed_kmh": 90.0}
    tire_circ = 2.0  # 2 m circumference
    result = _wheel_hz(sample, tire_circ)
    assert result is not None
    expected = (90.0 / 3.6) / 2.0
    assert abs(result - expected) < 1e-9


def test_wheel_hz_no_speed() -> None:
    assert _wheel_hz({"speed_kmh": None}, 2.0) is None
    assert _wheel_hz({"speed_kmh": 0}, 2.0) is None


def test_wheel_hz_no_tire() -> None:
    assert _wheel_hz({"speed_kmh": 90.0}, None) is None
    assert _wheel_hz({"speed_kmh": 90.0}, 0.0) is None


# -- _effective_engine_rpm -----------------------------------------------------


def test_effective_engine_rpm_measured() -> None:
    sample = {"engine_rpm": 3000.0, "engine_rpm_source": "obd"}
    rpm, src = _effective_engine_rpm(sample, {}, None)
    assert rpm == 3000.0
    assert src == "obd"


def test_effective_engine_rpm_estimated_from_speed() -> None:
    tire_circ = 2.0
    sample = {"speed_kmh": 90.0, "gear": 0.64, "final_drive_ratio": 3.08}
    rpm, src = _effective_engine_rpm(sample, {}, tire_circ)
    assert rpm is not None
    assert rpm > 0
    assert src == "estimated_from_speed_and_ratios"


def test_effective_engine_rpm_missing() -> None:
    rpm, src = _effective_engine_rpm({}, {}, None)
    assert rpm is None
    assert src == "missing"


# -- _corr_abs -----------------------------------------------------------------


def test_corr_abs_perfect_positive() -> None:
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 6.0, 8.0, 10.0]
    result = _corr_abs(x, y)
    assert result is not None
    assert abs(result - 1.0) < 1e-9


def test_corr_abs_perfect_negative() -> None:
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [10.0, 8.0, 6.0, 4.0, 2.0]
    result = _corr_abs(x, y)
    assert result is not None
    assert abs(result - 1.0) < 1e-9


def test_corr_abs_too_few_points() -> None:
    assert _corr_abs([1.0, 2.0], [3.0, 4.0]) is None


def test_corr_abs_constant_returns_none() -> None:
    assert _corr_abs([1.0, 1.0, 1.0], [2.0, 3.0, 4.0]) is None
