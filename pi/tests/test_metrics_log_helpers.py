from __future__ import annotations

from vibesensor.metrics_log import MetricsLogger

# -- MetricsLogger._safe_metric ------------------------------------------------


def test_safe_metric_valid() -> None:
    metrics = {"x": {"rms": 0.05, "p2p": 0.12}}
    result = MetricsLogger._safe_metric(metrics, "x", "rms")
    assert result == 0.05


def test_safe_metric_missing_axis() -> None:
    metrics = {"x": {"rms": 0.05}}
    assert MetricsLogger._safe_metric(metrics, "y", "rms") is None


def test_safe_metric_missing_key() -> None:
    metrics = {"x": {"rms": 0.05}}
    assert MetricsLogger._safe_metric(metrics, "x", "p2p") is None


def test_safe_metric_nan_returns_none() -> None:
    metrics = {"x": {"rms": float("nan")}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_inf_returns_none() -> None:
    metrics = {"x": {"rms": float("inf")}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_axis_not_dict_returns_none() -> None:
    metrics = {"x": "not_a_dict"}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_non_numeric_returns_none() -> None:
    metrics = {"x": {"rms": "abc"}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


# -- MetricsLogger._dominant_peak ----------------------------------------------


def test_dominant_peak_from_combined() -> None:
    metrics = {
        "combined": {"peaks": [{"hz": 15.0, "amp": 0.3}]},
        "x": {"peaks": [{"hz": 20.0, "amp": 0.5}]},
    }
    hz, amp, axis = MetricsLogger._dominant_peak(metrics)
    assert hz == 15.0
    assert amp == 0.3
    assert axis == "combined"


def test_dominant_peak_fallback_to_axis() -> None:
    metrics = {
        "combined": {},
        "x": {"peaks": [{"hz": 20.0, "amp": 0.5}]},
        "y": {"peaks": [{"hz": 30.0, "amp": 0.8}]},
    }
    hz, amp, axis = MetricsLogger._dominant_peak(metrics)
    assert hz == 30.0
    assert amp == 0.8
    assert axis == "y"


def test_dominant_peak_no_peaks() -> None:
    metrics = {"x": {}, "y": {}, "z": {}}
    hz, amp, axis = MetricsLogger._dominant_peak(metrics)
    assert hz is None
    assert amp is None
    assert axis is None


def test_dominant_peak_skips_nan_peaks() -> None:
    metrics = {
        "combined": {"peaks": [{"hz": float("nan"), "amp": 0.3}]},
        "x": {"peaks": [{"hz": 10.0, "amp": 0.2}]},
    }
    hz, amp, axis = MetricsLogger._dominant_peak(metrics)
    assert hz == 10.0
    assert axis == "x"


def test_dominant_peak_skips_negative_hz() -> None:
    metrics = {
        "combined": {"peaks": [{"hz": -1.0, "amp": 0.3}]},
    }
    hz, amp, axis = MetricsLogger._dominant_peak(metrics)
    # Negative hz skipped; combined peak ignored, fallback to axes
    assert hz is None


def test_dominant_peak_skips_negative_amp() -> None:
    metrics = {
        "combined": {"peaks": [{"hz": 10.0, "amp": -0.1}]},
    }
    hz, amp, axis = MetricsLogger._dominant_peak(metrics)
    assert hz is None
