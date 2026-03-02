"""Unit tests for vibesensor.metrics_log.sample_builder.

These tests exercise the pure functions extracted from MetricsLogger,
validating that they work independently of any session lifecycle or
threading machinery.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vibesensor.metrics_log.sample_builder import (
    build_run_metadata,
    build_sample_records,
    dominant_hz_from_strength,
    extract_axis_top_peaks,
    extract_strength_data,
    firmware_version_for_run,
    resolve_speed_context,
    safe_metric,
)

# ---------------------------------------------------------------------------
# safe_metric
# ---------------------------------------------------------------------------


class TestSafeMetric:
    def test_valid_float(self) -> None:
        assert safe_metric({"x": {"rms": 0.05}}, "x", "rms") == 0.05

    def test_missing_axis(self) -> None:
        assert safe_metric({"x": {"rms": 0.05}}, "y", "rms") is None

    def test_missing_key(self) -> None:
        assert safe_metric({"x": {"rms": 0.05}}, "x", "p2p") is None

    def test_nan(self) -> None:
        assert safe_metric({"x": {"rms": float("nan")}}, "x", "rms") is None

    def test_inf(self) -> None:
        assert safe_metric({"x": {"rms": float("inf")}}, "x", "rms") is None

    def test_non_numeric(self) -> None:
        assert safe_metric({"x": {"rms": "abc"}}, "x", "rms") is None

    def test_non_dict_axis(self) -> None:
        assert safe_metric({"x": "not_dict"}, "x", "rms") is None


# ---------------------------------------------------------------------------
# extract_strength_data
# ---------------------------------------------------------------------------


class TestExtractStrengthData:
    def test_with_root_strength_metrics(self) -> None:
        metrics = {
            "strength_metrics": {
                "vibration_strength_db": 22.0,
                "strength_bucket": "l2",
                "peak_amp_g": 0.15,
                "noise_floor_amp_g": 0.003,
                "top_peaks": [
                    {
                        "hz": 15.0,
                        "amp": 0.12,
                        "vibration_strength_db": 22.0,
                        "strength_bucket": "l2",
                    },
                ],
            },
        }
        sm, db_val, bucket, peak, floor, peaks = extract_strength_data(metrics)
        assert db_val == 22.0
        assert bucket == "l2"
        assert peak == 0.15
        assert floor == 0.003
        assert len(peaks) == 1
        assert peaks[0]["hz"] == 15.0

    def test_empty_metrics(self) -> None:
        sm, db_val, bucket, peak, floor, peaks = extract_strength_data({})
        assert db_val is None
        assert bucket is None
        assert peak is None
        assert floor is None
        assert peaks == []

    def test_invalid_peak_skipped(self) -> None:
        metrics = {
            "strength_metrics": {
                "top_peaks": [
                    {"hz": "bad", "amp": 0.1},  # non-numeric
                    {"hz": 0, "amp": 0.1},  # zero hz
                    {"hz": 10.0, "amp": float("nan")},  # nan amp
                ],
            },
        }
        _, _, _, _, _, peaks = extract_strength_data(metrics)
        assert peaks == []

    def test_max_8_peaks(self) -> None:
        metrics = {
            "strength_metrics": {
                "top_peaks": [{"hz": float(i), "amp": 0.01} for i in range(1, 12)],
            },
        }
        _, _, _, _, _, peaks = extract_strength_data(metrics)
        assert len(peaks) == 8


# ---------------------------------------------------------------------------
# extract_axis_top_peaks
# ---------------------------------------------------------------------------


class TestExtractAxisTopPeaks:
    def test_valid_peaks(self) -> None:
        metrics = {"x": {"peaks": [{"hz": 10.0, "amp": 0.05}, {"hz": 20.0, "amp": 0.03}]}}
        result = extract_axis_top_peaks(metrics, "x")
        assert len(result) == 2
        assert result[0] == {"hz": 10.0, "amp": 0.05}

    def test_max_3_peaks(self) -> None:
        metrics = {"x": {"peaks": [{"hz": float(i), "amp": 0.01} for i in range(1, 6)]}}
        result = extract_axis_top_peaks(metrics, "x")
        assert len(result) == 3

    def test_missing_axis(self) -> None:
        assert extract_axis_top_peaks({}, "x") == []


# ---------------------------------------------------------------------------
# dominant_hz_from_strength
# ---------------------------------------------------------------------------


class TestDominantHzFromStrength:
    def test_returns_first_peak_hz(self) -> None:
        sm = {"top_peaks": [{"hz": 42.0, "amp": 0.5}]}
        assert dominant_hz_from_strength(sm) == 42.0

    def test_empty(self) -> None:
        assert dominant_hz_from_strength({}) is None

    def test_no_peaks(self) -> None:
        assert dominant_hz_from_strength({"top_peaks": []}) is None


# ---------------------------------------------------------------------------
# resolve_speed_context
# ---------------------------------------------------------------------------


class TestResolveSpeedContext:
    def test_no_speed(self) -> None:
        gps = MagicMock()
        gps.speed_mps = None
        gps.effective_speed_mps = None
        gps.resolve_speed.return_value = MagicMock(source="none")
        settings = {}
        speed, gps_speed, source, rpm, fdr, gr = resolve_speed_context(gps, settings)
        assert speed is None
        assert rpm is None
        assert source == "none"

    def test_gps_speed(self) -> None:
        gps = MagicMock()
        gps.speed_mps = 10.0
        gps.effective_speed_mps = 10.0
        gps.resolve_speed.return_value = MagicMock(source="gps")
        settings = {
            "tire_width_mm": 205.0,
            "tire_aspect_pct": 55.0,
            "rim_in": 16.0,
            "final_drive_ratio": 3.73,
            "current_gear_ratio": 1.0,
        }
        speed, gps_speed, source, rpm, fdr, gr = resolve_speed_context(gps, settings)
        assert speed == pytest.approx(36.0, rel=0.01)
        assert source == "gps"
        assert rpm is not None and rpm > 0


# ---------------------------------------------------------------------------
# firmware_version_for_run
# ---------------------------------------------------------------------------


class TestFirmwareVersionForRun:
    def test_no_clients(self) -> None:
        reg = MagicMock()
        reg.active_client_ids.return_value = []
        assert firmware_version_for_run(reg) is None

    def test_single_version(self) -> None:
        record = MagicMock()
        record.firmware_version = "1.2.3"
        reg = MagicMock()
        reg.active_client_ids.return_value = ["c1"]
        reg.get.return_value = record
        assert firmware_version_for_run(reg) == "1.2.3"

    def test_multiple_versions_sorted(self) -> None:
        def _get(cid: str):
            m = MagicMock()
            m.firmware_version = {"c1": "1.0.0", "c2": "2.0.0"}[cid]
            return m

        reg = MagicMock()
        reg.active_client_ids.return_value = ["c1", "c2"]
        reg.get.side_effect = _get
        assert firmware_version_for_run(reg) == "1.0.0, 2.0.0"


# ---------------------------------------------------------------------------
# build_run_metadata
# ---------------------------------------------------------------------------


class TestBuildRunMetadata:
    def test_basic(self) -> None:
        meta = build_run_metadata(
            run_id="test-run",
            start_time_utc="2026-01-01T00:00:00Z",
            analysis_settings_snapshot={
                "tire_width_mm": 205.0,
                "tire_aspect_pct": 55.0,
                "rim_in": 16.0,
            },
            sensor_model="ADXL345",
            firmware_version=None,
            default_sample_rate_hz=800,
            metrics_log_hz=4,
            fft_window_size_samples=1024,
            fft_window_type="hann",
            peak_picker_method="canonical",
            accel_scale_g_per_lsb=None,
        )
        assert meta["run_id"] == "test-run"
        assert meta["sensor_model"] == "ADXL345"
        assert meta["tire_width_mm"] == 205.0

    def test_with_language(self) -> None:
        meta = build_run_metadata(
            run_id="run-lang",
            start_time_utc="2026-01-01T00:00:00Z",
            analysis_settings_snapshot={},
            sensor_model="test",
            firmware_version=None,
            default_sample_rate_hz=800,
            metrics_log_hz=4,
            fft_window_size_samples=512,
            fft_window_type="hann",
            peak_picker_method="test",
            accel_scale_g_per_lsb=None,
            language_provider=lambda: "fi",
        )
        assert meta["language"] == "fi"


# ---------------------------------------------------------------------------
# build_sample_records
# ---------------------------------------------------------------------------


class TestBuildSampleRecords:
    def test_no_active_clients(self) -> None:
        reg = MagicMock()
        proc = MagicMock()
        gps = MagicMock()
        gps.speed_mps = None
        gps.effective_speed_mps = None
        gps.resolve_speed.return_value = MagicMock(source="none")
        proc.clients_with_recent_data.return_value = []
        records = build_sample_records(
            run_id="r1",
            t_s=0.0,
            timestamp_utc="2026-01-01T00:00:00Z",
            registry=reg,
            processor=proc,
            gps_monitor=gps,
            analysis_settings_snapshot={},
            default_sample_rate_hz=800,
        )
        assert records == []
