"""Tests for RunAnalysis and PreparedRunData convenience properties."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter
from test_support.sample_scenarios import make_analysis_sample

from vibesensor.adapters.analysis_summary import (
    analysis_result_to_summary,
    summarize_run_data,
)
from vibesensor.domain import SpeedProfile
from vibesensor.shared.boundaries.sensor_frame_codec import normalize_sensor_frames
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.use_cases.diagnostics._context_decode import build_diagnostics_context
from vibesensor.use_cases.diagnostics.run_data_preparation import (
    PreparedRunData,
    build_phase_summary,
    prepare_run_data,
)
from vibesensor.use_cases.diagnostics.speed_profile_helpers import _speed_stats
from vibesensor.use_cases.diagnostics.summary_builder import RunAnalysis


def _analysis(
    metadata: dict[str, object],
    samples: list[dict[str, object]],
    **kwargs: object,
) -> RunAnalysis:
    file_name = str(kwargs.get("file_name") or "run")
    return RunAnalysis(
        build_diagnostics_context(metadata, file_name=file_name),
        normalize_sensor_frames(samples),
        **kwargs,
    )


def _prepared_with_speed_profile(
    *,
    speed_profile: SpeedProfile,
    speed_values: list[float] | None = None,
) -> PreparedRunData:
    return PreparedRunData(
        run_id="run-1",
        start_ts=datetime.now(UTC),
        end_ts=datetime.now(UTC),
        duration_s=10.0,
        raw_sample_rate_hz=100.0,
        speed_values=list(speed_values or []),
        speed_non_null_pct=100.0,
        speed_sufficient=True,
        per_sample_phases=[],
        phase_segments=[],
        run_noise_baseline_g=None,
        speed_profile=speed_profile,
        speed_stats_by_phase={},
        speed_breakdown=[],
        speed_breakdown_skipped_reason=None,
        phase_speed_breakdown=[],
    )


# ===========================================================================
# PreparedRunData convenience properties
# ===========================================================================


class TestPreparedRunDataProperties:
    def test_is_steady_speed_reads_speed_profile(self) -> None:
        prepared = _prepared_with_speed_profile(
            speed_profile=SpeedProfile(steady_speed=True),
            speed_values=[60.0, 60.0],
        )

        assert prepared.is_steady_speed is True

    def test_speed_stddev_kmh_reads_speed_profile(self) -> None:
        prepared = _prepared_with_speed_profile(
            speed_profile=SpeedProfile(stddev_kmh=1.25),
            speed_values=[58.0, 60.0, 62.0],
        )

        assert prepared.speed_stddev_kmh == pytest.approx(1.25)

    def test_speed_stddev_kmh_none_without_speed_values(self) -> None:
        prepared = _prepared_with_speed_profile(
            speed_profile=SpeedProfile(stddev_kmh=1.25),
            speed_values=[],
        )

        assert prepared.speed_stddev_kmh is None

    def test_speed_profile_exposed_with_phase_aware_content(self) -> None:
        metadata = {"raw_sample_rate_hz": 100.0}
        speeds = [0.0, 0.0, 0.0, 10.0, 20.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0]
        samples = [
            {"speed_kmh": speed_kmh, "t_s": float(index), "vibration_strength_db": 10.0}
            for index, speed_kmh in enumerate(speeds)
        ]

        context = build_diagnostics_context(metadata, file_name="test")
        prepared = prepare_run_data(context, normalize_sensor_frames(samples))
        speed_stats = _speed_stats(prepared.speed_values)
        phase_info = build_phase_summary(prepared.phase_segments)

        assert prepared.speed_profile == SpeedProfile.from_stats(
            speed_stats,
            phase_info,
        )
        assert prepared.speed_profile.min_kmh == pytest.approx(speed_stats.min_kmh)
        assert prepared.speed_profile.max_kmh == pytest.approx(speed_stats.max_kmh)
        assert prepared.speed_profile.has_acceleration is True
        assert prepared.speed_profile.has_cruise is True
        assert prepared.speed_profile.idle_fraction > 0.0


# ===========================================================================
# RunAnalysis
# ===========================================================================


class TestRunAnalysis:
    def test_summarize_returns_summary_data(self) -> None:
        """Minimal smoke test: RunAnalysis.summarize() produces an AnalysisResult."""
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
        analysis = _analysis(metadata, samples, file_name="test_run")
        result = analysis.summarize()
        summary = analysis_result_to_summary(result)
        assert "findings" in summary
        assert "run_id" in summary
        assert summary["file_name"] == "test_run"
        assert result.test_run is not None
        assert result.diagnostic_case is not None

    def test_summarize_matches_function_api(self) -> None:
        """RunAnalysis.summarize() should produce identical output to summarize_run_data()."""
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
        summary_via_class = analysis_result_to_summary(
            _analysis(metadata, samples, file_name="f").summarize(),
        )
        # Key structural fields should match
        assert summary_via_function["run_id"] == summary_via_class["run_id"]
        assert summary_via_function["rows"] == summary_via_class["rows"]
        assert len(summary_via_function["findings"]) == len(summary_via_class["findings"])

    def test_prepared_property(self) -> None:
        metadata = {"raw_sample_rate_hz": 100.0}
        samples = [{"speed_kmh": 60.0, "t_s": 0.0, "vibration_strength_db": 10.0}]
        analysis = _analysis(metadata, samples)
        assert isinstance(analysis.prepared, PreparedRunData)
        assert isinstance(analysis.prepared.speed_profile, SpeedProfile)

    def test_language_property(self) -> None:
        metadata = {}
        samples = [{"t_s": 0.0, "vibration_strength_db": 10.0}]
        analysis = _analysis(metadata, samples, lang="en")
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
        analysis = _analysis(metadata, samples, include_samples=False)
        result = analysis.summarize()
        assert "samples" not in analysis_result_to_summary(result)

    def test_typed_samples_serialize_at_summary_boundary(self) -> None:
        metadata = {"raw_sample_rate_hz": 100.0}
        samples = [
            make_analysis_sample(
                t_s=0.0,
                speed_kmh=60.0,
                client_name="FL",
                top_peaks=[{"hz": 14.0, "amp": 0.05}],
                vibration_strength_db=10.0,
                accel_x_g=0.01,
                accel_y_g=0.01,
                accel_z_g=0.01,
            ),
        ]

        summary = analysis_result_to_summary(
            _analysis(metadata, samples, file_name="typed-run").summarize(),
        )

        assert summary["samples"][0]["client_name"] == "FL"
        assert summary["samples"][0]["top_peaks"] == [{"hz": 14.0, "amp": 0.05}]

    def test_summary_matches_typed_boundary_contract(self) -> None:
        metadata = {
            "run_id": "fuzz-contract-repro",
            "start_time_utc": "2026-01-01T12:00:00Z",
            "sensor_model": "ADXL345",
        }

        summary = summarize_run_data(
            metadata,
            [],
            lang="en",
            include_samples=False,
        )

        assert "_summary_version" not in summary
        TypeAdapter(AnalysisSummary).validate_python(summary)
