from __future__ import annotations

from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_WHOLE_RUN_ALIGNMENT_INCOMPLETE,
    RunContextWarning,
)
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunSpectralBuildResult,
    WholeRunSpectralCoverageSummary,
)
from vibesensor.use_cases.run.post_analysis_executor import execute_post_analysis
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_outcomes import PostAnalysisExecutionSuccess


def _run_metadata(run_id: str) -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "language": "en",
        }
    )


def _samples() -> list:
    return sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}])


def test_execute_post_analysis_appends_whole_run_alignment_warning_and_metadata() -> None:
    stored: dict[str, object] = {}
    raw_capture_manifest = RawCaptureManifest(
        run_id="run-whole-run-warning",
        relative_dir="raw-runs/run-whole-run-warning",
        sensors=(),
        total_samples=0,
        total_bytes=0,
        created_at="2025-01-01T00:00:00Z",
    )

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            stored["analysis_run_id"] = run_id
            stored["analysis"] = analysis

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    result = execute_post_analysis(
        run_id="run-whole-run-warning",
        db=FakeDB(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id),
            language="en",
            samples=_samples(),
            total_sample_count=1,
            stride=1,
            raw_capture=RawRunCapture(manifest=raw_capture_manifest, sensors=()),
            raw_capture_manifest=raw_capture_manifest,
        ),
        whole_run_artifact_builder=lambda **_kwargs: WholeRunSpectralBuildResult(
            bundle=None,
            coverage_summary=WholeRunSpectralCoverageSummary(
                total_sensor_window_count=4,
                full_sensor_window_count=2,
                partial_sensor_window_count=1,
                missing_sensor_window_count=1,
                empty_sensor_window_count=0,
                gap_count=1,
                overlap_count=0,
                dropped_chunk_count=2,
                queue_overflow_chunk_count=2,
                invalid_chunk_count=0,
                write_error_chunk_count=0,
                sample_rate_mismatch_sensor_count=1,
                unanchored_sensor_count=1,
                legacy_sensor_count=0,
                sync_unverified_sensor_count=1,
                stale_sync_sensor_count=1,
                high_rtt_sensor_count=0,
                coverage_confidence="partial",
                warnings=(
                    RunContextWarning(
                        code=WARNING_CODE_WHOLE_RUN_ALIGNMENT_INCOMPLETE,
                        severity="warn",
                        applies_to="whole_run",
                        title=i18n_ref("RUN_CONTEXT_WARNING_WHOLE_RUN_ALIGNMENT_INCOMPLETE_TITLE"),
                        detail=i18n_ref(
                            "RUN_CONTEXT_WARNING_WHOLE_RUN_ALIGNMENT_INCOMPLETE_DETAIL",
                            partial="1",
                            missing="1",
                            gaps="1",
                            overlaps="0",
                            dropped="2",
                            queue_overflow="2",
                            invalid="0",
                            write_errors="0",
                            mismatches="1",
                            legacy="0",
                            unanchored="1",
                            sync_unverified="1",
                            missing_sync="0",
                            stale="1",
                            high_rtt="0",
                        ),
                    ),
                ),
            ),
        ),
        whole_run_context_builder=lambda **_kwargs: None,
        analysis_runner=lambda _run: make_persisted_analysis(
            {
                "analysis_metadata": {
                    "analyzed_sample_count": 1,
                    "total_sample_count": 1,
                    "sampling_method": "full",
                },
                "run_suitability": [],
            }
        ),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    analysis_metadata = stored["analysis"]["analysis_metadata"]
    assert analysis_metadata["whole_run_spectral_available"] is False
    assert analysis_metadata["whole_run_spectral_sensor_window_count"] == 4
    assert analysis_metadata["whole_run_spectral_partial_sensor_window_count"] == 1
    assert analysis_metadata["whole_run_spectral_missing_sensor_window_count"] == 1
    assert analysis_metadata["whole_run_spectral_gap_count"] == 1
    assert analysis_metadata["whole_run_spectral_sample_rate_mismatch_sensor_count"] == 1
    assert analysis_metadata["whole_run_spectral_sync_unverified_sensor_count"] == 1
    assert analysis_metadata["whole_run_spectral_coverage_confidence"] == "partial"
    assert [warning["code"] for warning in stored["analysis"]["warnings"]] == [
        WARNING_CODE_WHOLE_RUN_ALIGNMENT_INCOMPLETE
    ]
