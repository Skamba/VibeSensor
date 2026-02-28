from __future__ import annotations

import pytest
from vibesensor_core.vibration_strength import percentile

from vibesensor.analysis.helpers import (
    _corr_abs,
    _effective_engine_rpm,
    _format_duration,
    _location_label,
    _locations_connected_throughout_run,
    _mean_variance,
    _outlier_summary,
    _percent_missing,
    _primary_vibration_strength_db,
    _sample_top_peaks,
    _sensor_limit_g,
    _speed_bin_label,
    _speed_bin_sort_key,
    _speed_stats,
    _speed_stats_by_phase,
)
from vibesensor.analysis.order_analysis import _wheel_hz
from vibesensor.constants import KMH_TO_MPS
from vibesensor.report_i18n import normalize_lang
from vibesensor.runlog import as_float_or_none as _as_float

# -- normalize_lang -----------------------------------------------------------


def test_normalize_lang_en_default() -> None:
    assert normalize_lang("en") == "en"
    assert normalize_lang("EN") == "en"
    assert normalize_lang("") == "en"
    assert normalize_lang(None) == "en"
    assert normalize_lang(42) == "en"


def test_normalize_lang_nl() -> None:
    assert normalize_lang("nl") == "nl"
    assert normalize_lang("NL") == "nl"
    assert normalize_lang("nl-NL") == "nl"


# -- _as_float -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(3.14, 3.14, id="float"),
        pytest.param(0, 0.0, id="int_zero"),
        pytest.param("2.5", 2.5, id="numeric_string"),
        pytest.param(None, None, id="none"),
        pytest.param("", None, id="empty_string"),
        pytest.param("abc", None, id="non_numeric_string"),
        pytest.param(float("nan"), None, id="nan"),
    ],
)
def test_as_float(value: object, expected: float | None) -> None:
    assert _as_float(value) is expected if expected is None else _as_float(value) == expected


# -- _format_duration ----------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        pytest.param(0, "00:00.0", id="zero"),
        pytest.param(90.0, "01:30.0", id="90s"),
        pytest.param(-5.0, "00:00.0", id="negative_clamped"),
        pytest.param(65.3, "01:05.3", id="fractional"),
        pytest.param(59.96, "01:00.0", id="60s_boundary_low"),
        pytest.param(119.96, "02:00.0", id="60s_boundary_high"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert _format_duration(seconds) == expected


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
    # sample var = ((2-4)^2 + (4-4)^2 + (6-4)^2) / (3-1) = 8/2 = 4.0
    assert abs(v - 4.0) < 1e-9


def test_mean_variance_empty() -> None:
    m, v = _mean_variance([])
    assert m is None
    assert v is None


def test_mean_variance_single_value() -> None:
    m, v = _mean_variance([42.0])
    assert m is not None
    assert abs(m - 42.0) < 1e-9
    assert v is not None
    assert abs(v - 0.0) < 1e-9  # single value → zero variance


def test_mean_variance_two_values_sample_variance() -> None:
    """Two values: sample variance (N-1) differs from population variance (N)."""
    m, v = _mean_variance([100.0, 102.0])
    assert m is not None
    assert abs(m - 101.0) < 1e-9
    assert v is not None
    # sample var = ((100-101)^2 + (102-101)^2) / (2-1) = 2.0
    assert abs(v - 2.0) < 1e-9


# -- percentile ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("sorted_vals", "q", "expected"),
    [
        pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], 0.5, 3.0, id="median"),
        pytest.param([], 0.5, 0.0, id="empty"),
        pytest.param([7.0], 0.5, 7.0, id="single_element"),
        pytest.param([10.0, 20.0, 30.0], 0.0, 10.0, id="q0_min"),
        pytest.param([10.0, 20.0, 30.0], 1.0, 30.0, id="q1_max"),
    ],
)
def test_percentile(sorted_vals: list[float], q: float, expected: float) -> None:
    assert percentile(sorted_vals, q) == pytest.approx(expected, abs=1e-9)


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
    assert result["steady_speed"] is False


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


# -- _speed_stats_by_phase -----------------------------------------------------


def test_speed_stats_by_phase_empty() -> None:
    result = _speed_stats_by_phase([], [])
    assert result == {}


def test_speed_stats_by_phase_single_phase() -> None:
    samples = [
        {"speed_kmh": 60.0},
        {"speed_kmh": 61.0},
        {"speed_kmh": 60.5},
    ]
    phases = ["cruise", "cruise", "cruise"]
    result = _speed_stats_by_phase(samples, phases)
    assert "cruise" in result
    assert result["cruise"]["sample_count"] == 3
    assert result["cruise"]["min_kmh"] == 60.0
    assert result["cruise"]["max_kmh"] == 61.0


def test_speed_stats_by_phase_multiple_phases() -> None:
    samples = [
        {"speed_kmh": 1.0},
        {"speed_kmh": 1.0},
        {"speed_kmh": 60.0},
        {"speed_kmh": 61.0},
        {"speed_kmh": 62.0},
    ]
    phases = ["idle", "idle", "cruise", "cruise", "cruise"]
    result = _speed_stats_by_phase(samples, phases)
    assert set(result.keys()) == {"idle", "cruise"}
    assert result["idle"]["sample_count"] == 2
    assert result["cruise"]["sample_count"] == 3
    assert result["cruise"]["min_kmh"] == 60.0


def test_speed_stats_by_phase_excludes_zero_and_none_speed() -> None:
    """Speed values of 0 or None should not contribute to per-phase speed stats."""
    samples = [
        {"speed_kmh": 0.0},
        {"speed_kmh": None},
        {"speed_kmh": 50.0},
    ]
    phases = ["idle", "idle", "cruise"]
    result = _speed_stats_by_phase(samples, phases)
    # idle has 2 samples but none with speed > 0
    assert result["idle"]["sample_count"] == 2
    assert result["idle"]["min_kmh"] is None
    # cruise has valid speed
    assert result["cruise"]["min_kmh"] == 50.0


def test_speed_stats_by_phase_sample_count_sums_to_total() -> None:
    from vibesensor.analysis.phase_segmentation import segment_run_phases

    samples = [
        {"t_s": float(i), "speed_kmh": 0.5 if i < 5 else 60.0, "vibration_strength_db": 10.0}
        for i in range(10)
    ]
    per_sample_phases, _ = segment_run_phases(samples)
    result = _speed_stats_by_phase(samples, per_sample_phases)
    total = sum(v["sample_count"] for v in result.values())
    assert total == len(samples)


@pytest.mark.parametrize(
    ("sensor", "expected"),
    [
        pytest.param("ADXL345", 16.0, id="adxl345"),
        pytest.param("my-adxl345-board", 16.0, id="adxl345_substring"),
        pytest.param("LIS3DH", None, id="unknown_chip"),
        pytest.param(None, None, id="none"),
        pytest.param(42, None, id="non_string"),
    ],
)
def test_sensor_limit_g(sensor: object, expected: float | None) -> None:
    assert _sensor_limit_g(sensor) == expected


# -- _primary_vibration_strength_db -------------------------------------------


def test_primary_vibration_strength_db_reads_canonical_field() -> None:
    sample = {"vibration_strength_db": 22.5}
    assert _primary_vibration_strength_db(sample) == 22.5


def test_primary_vibration_strength_db_returns_none_for_missing() -> None:
    assert _primary_vibration_strength_db({}) is None
    # Old g-based fields are no longer supported.
    assert _primary_vibration_strength_db({"vib_mag_rms_g": 0.04}) is None


# -- _sample_top_peaks ---------------------------------------------------------


def test_sample_top_peaks_from_top_peaks_field() -> None:
    sample = {"top_peaks": [{"hz": 15.0, "amp": 0.1}, {"hz": 30.0, "amp": 0.2}]}
    peaks = _sample_top_peaks(sample)
    assert len(peaks) == 2
    assert peaks[0] == (15.0, 0.1)


def test_sample_top_peaks_returns_empty_without_top_peaks_key() -> None:
    # No top_peaks key → returns empty list (no fallback to dominant_freq_hz)
    sample = {"dominant_freq_hz": 25.0, "vibration_strength_db": 22.0}
    peaks = _sample_top_peaks(sample)
    assert len(peaks) == 0


def test_sample_top_peaks_filters_invalid() -> None:
    sample = {"top_peaks": [{"hz": -1.0, "amp": 0.1}, {"hz": 10.0, "amp": None}]}
    peaks = _sample_top_peaks(sample)
    assert len(peaks) == 0


def test_sample_top_peaks_filters_sub_min_analysis_freq() -> None:
    """Peaks below MIN_ANALYSIS_FREQ_HZ (5.0 Hz) should be excluded."""
    from vibesensor.analysis.helpers import MIN_ANALYSIS_FREQ_HZ

    sample = {
        "top_peaks": [
            {"hz": 1.5, "amp": 0.2},  # below MIN_ANALYSIS_FREQ_HZ
            {"hz": 2.9, "amp": 0.15},  # below MIN_ANALYSIS_FREQ_HZ
            {"hz": 3.0, "amp": 0.1},  # below MIN_ANALYSIS_FREQ_HZ
            {"hz": 4.9, "amp": 0.08},  # below MIN_ANALYSIS_FREQ_HZ
            {"hz": 5.0, "amp": 0.07},  # at boundary — should pass
            {"hz": 15.0, "amp": 0.05},  # well above — should pass
        ]
    }
    peaks = _sample_top_peaks(sample)
    assert len(peaks) == 2
    assert all(hz >= MIN_ANALYSIS_FREQ_HZ for hz, _ in peaks)


# -- _location_label -----------------------------------------------------------


@pytest.mark.parametrize(
    ("info", "lang", "expected"),
    [
        pytest.param({"client_name": "Front Left"}, "en", "Front Left", id="name_en"),
        pytest.param({"client_id": "AB:CD:EF:12:34:56"}, "en", "Sensor \u20264:56", id="client_id_en"),
        pytest.param({}, "en", "Unknown sensor", id="unlabeled_en"),
        pytest.param({}, "nl", "Unknown sensor", id="unlabeled_nl_neutral"),
        pytest.param({"client_id": "AB:CD:EF:12:34:56"}, "nl", "Sensor \u20264:56", id="client_id_nl_neutral"),
    ],
)
def test_location_label(info: dict, lang: str, expected: str) -> None:
    assert _location_label(info, lang=lang) == expected


def test_locations_connected_throughout_requires_mid_run_continuity() -> None:
    samples = []
    for t_s in (0.0, 1.0, 2.0, 8.0, 9.0, 10.0):
        samples.append({"t_s": t_s, "client_name": "Front Left"})
    for t_s in range(0, 11):
        samples.append({"t_s": float(t_s), "client_name": "Rear Right"})
    connected = _locations_connected_throughout_run(samples)
    assert connected == {"Rear Right"}


def test_locations_connected_throughout_can_be_empty() -> None:
    samples = [
        {"t_s": 2.0, "client_name": "Front Left"},
        {"t_s": 5.0, "client_name": "Front Left"},
        {"t_s": 8.0, "client_name": "Rear Right"},
    ]
    assert _locations_connected_throughout_run(samples) == set()


def test_locations_connected_throughout_deduplicates_timestamps() -> None:
    samples = []
    for _ in range(10):
        samples.append({"t_s": 0.0, "client_name": "Front Left"})
        samples.append({"t_s": 10.0, "client_name": "Front Left"})
    for t_s in range(0, 11):
        samples.append({"t_s": float(t_s), "client_name": "Rear Right"})
    connected = _locations_connected_throughout_run(samples)
    assert connected == {"Rear Right"}


# -- _wheel_hz -----------------------------------------------------------------


def test_wheel_hz_basic() -> None:
    sample = {"speed_kmh": 90.0}
    tire_circ = 2.0  # 2 m circumference
    result = _wheel_hz(sample, tire_circ)
    assert result is not None
    expected = (90.0 * KMH_TO_MPS) / 2.0
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
