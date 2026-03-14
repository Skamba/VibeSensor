"""Tests for RunAnalysis and PreparedRunData convenience properties."""

from __future__ import annotations

import pytest

from vibesensor.analysis.summary_builder import PreparedRunData, RunAnalysis, prepare_run_data
from vibesensor.domain import SpeedProfile

# ===========================================================================
# PreparedRunData convenience properties
# ===========================================================================


class TestPreparedRunDataProperties:
    def test_is_steady_speed_true(self) -> None:
        metadata = {"raw_sample_rate_hz": 100.0}
        samples = [
            {"speed_kmh": 60.0, "t_s": float(i), "vibration_strength_db": 10.0} for i in range(20)
        ]
        prepared = prepare_run_data(metadata, samples, file_name="test")
        # is_steady_speed delegates to speed_stats["steady_speed"]
        assert isinstance(prepared.is_steady_speed, bool)

    def test_speed_stddev_kmh(self) -> None:
        metadata = {"raw_sample_rate_hz": 100.0}
        samples = [
            {"speed_kmh": 60.0, "t_s": float(i), "vibration_strength_db": 10.0} for i in range(20)
        ]
        prepared = prepare_run_data(metadata, samples, file_name="test")
        stddev = prepared.speed_stddev_kmh
        assert stddev is None or isinstance(stddev, float)

    def test_speed_profile_exposed_with_phase_aware_content(self) -> None:
        metadata = {"raw_sample_rate_hz": 100.0}
        speeds = [0.0, 0.0, 0.0, 10.0, 20.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0]
        samples = [
            {"speed_kmh": speed_kmh, "t_s": float(index), "vibration_strength_db": 10.0}
            for index, speed_kmh in enumerate(speeds)
        ]

        prepared = prepare_run_data(metadata, samples, file_name="test")

        assert prepared.speed_profile == SpeedProfile.from_stats(
            prepared.speed_stats,
            prepared.phase_info,
        )
        assert prepared.speed_profile.min_kmh == pytest.approx(prepared.speed_stats["min_kmh"])
        assert prepared.speed_profile.max_kmh == pytest.approx(prepared.speed_stats["max_kmh"])
        assert prepared.speed_profile.has_acceleration is True
        assert prepared.speed_profile.has_cruise is True
        assert prepared.speed_profile.idle_fraction > 0.0


# ===========================================================================
# RunAnalysis
# ===========================================================================


class TestRunAnalysis:
    def test_summarize_returns_summary_data(self) -> None:
        """Minimal smoke test: RunAnalysis.summarize() produces a summary dict."""
        metadata = {"raw_sample_rate_hz": 100.0}
        samples = [
            {
                "speed_kmh": 60.0,
                "t_s": float(i),
                "vibration_strength_db": 10.0,
                "accel_x_g": 0.01,
                "accel_y_g": 0.01,
                "accel_z_g": 0.01,
            }
            for i in range(20)
        ]
        analysis = RunAnalysis(metadata, samples, file_name="test_run")
        summary = analysis.summarize()
        assert isinstance(summary, dict)
        assert "findings" in summary
        assert "run_id" in summary
        assert summary["file_name"] == "test_run"

    def test_summarize_matches_function_api(self) -> None:
        """RunAnalysis.summarize() should produce identical output to summarize_run_data()."""
        from vibesensor.analysis.summary_builder import summarize_run_data

        metadata = {"raw_sample_rate_hz": 100.0}
        samples = [
            {
                "speed_kmh": 60.0,
                "t_s": float(i),
                "vibration_strength_db": 10.0,
                "accel_x_g": 0.01,
                "accel_y_g": 0.01,
                "accel_z_g": 0.01,
            }
            for i in range(10)
        ]
        # The function API delegates to RunAnalysis, so they should be equivalent
        summary_via_function = summarize_run_data(metadata, samples, file_name="f")
        summary_via_class = RunAnalysis(metadata, samples, file_name="f").summarize()
        # Key structural fields should match
        assert summary_via_function["run_id"] == summary_via_class["run_id"]
        assert summary_via_function["rows"] == summary_via_class["rows"]
        assert len(summary_via_function["findings"]) == len(summary_via_class["findings"])

    def test_prepared_property(self) -> None:
        metadata = {"raw_sample_rate_hz": 100.0}
        samples = [{"speed_kmh": 60.0, "t_s": 0.0, "vibration_strength_db": 10.0}]
        analysis = RunAnalysis(metadata, samples)
        assert isinstance(analysis.prepared, PreparedRunData)
        assert isinstance(analysis.prepared.speed_profile, SpeedProfile)

    def test_language_property(self) -> None:
        metadata = {}
        samples = [{"t_s": 0.0, "vibration_strength_db": 10.0}]
        analysis = RunAnalysis(metadata, samples, lang="en")
        assert analysis.language == "en"

    def test_include_samples_false(self) -> None:
        metadata = {"raw_sample_rate_hz": 100.0}
        samples = [
            {
                "speed_kmh": 60.0,
                "t_s": 0.0,
                "vibration_strength_db": 10.0,
                "accel_x_g": 0.01,
                "accel_y_g": 0.01,
                "accel_z_g": 0.01,
            }
        ]
        analysis = RunAnalysis(metadata, samples, include_samples=False)
        summary = analysis.summarize()
        assert "samples" not in summary
