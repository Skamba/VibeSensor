from __future__ import annotations

from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import (
    RawCaptureLossStats,
    RawCaptureManifest,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.run.post_analysis_executor import (
    PostAnalysisExecutionConfig,
    PostAnalysisWholeRunBuilderConfig,
    execute_post_analysis,
)
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_outcomes import PostAnalysisExecutionSuccess


def _run_metadata(run_id: str, *, language: str = "en") -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "language": language,
        }
    )


def _samples() -> list:
    return sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}])


def test_execute_post_analysis_skips_whole_run_artifacts_for_fatal_raw_capture_loss() -> None:
    stored: dict[str, object] = {}
    manifest = RawCaptureManifest(
        run_id="run-loss-gated",
        relative_dir="raw-runs/run-loss-gated",
        sensors=(),
        total_samples=0,
        total_bytes=0,
        created_at="2025-01-01T00:00:00Z",
        losses=RawCaptureLossStats(queue_overflow_chunk_count=120),
    )

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            stored["run_id"] = run_id
            stored["analysis"] = analysis

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    def artifact_builder(**_kwargs):
        raise AssertionError("fatal raw-capture loss must skip whole-run artifact build")

    def context_builder(**_kwargs):
        raise AssertionError("fatal raw-capture loss must skip whole-run context build")

    def analysis_runner(run: PostAnalysisRunInput):
        assert run.raw_replay.raw_capture_loss_policy_severity == "fatal"
        assert run.raw_replay.raw_capture_loss_policy_reason == "raw_capture_queue_overflow_fatal"
        assert run.raw_replay.raw_capture_loss_policy_gate_whole_run is True
        return make_persisted_analysis(
            {
                "lang": "en",
                "summary": {},
                "analysis_metadata": {
                    "raw_backed_sample_count": run.raw_backed_summary_row_count,
                    "raw_capture_mode": run.raw_replay.raw_capture_mode,
                    "raw_capture_loss_policy_severity": (
                        run.raw_replay.raw_capture_loss_policy_severity
                    ),
                    "raw_capture_loss_policy_reason": (
                        run.raw_replay.raw_capture_loss_policy_reason
                    ),
                    "raw_capture_loss_policy_gate_whole_run": (
                        run.raw_replay.raw_capture_loss_policy_gate_whole_run
                    ),
                },
            }
        )

    result = execute_post_analysis(
        run_id="run-loss-gated",
        db=FakeDB(),
        config=PostAnalysisExecutionConfig(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=_run_metadata(run_id, language="en"),
                language="en",
                samples=_samples(),
                raw_capture=RawRunCapture(manifest=manifest, sensors=()),
                total_summary_row_count=1,
                stride=1,
            ),
            analysis_runner=analysis_runner,
            whole_run_builders=PostAnalysisWholeRunBuilderConfig(
                artifact_builder=artifact_builder,
                context_builder=context_builder,
            ),
        ),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    assert "whole_run_run_id" not in stored
    assert (
        stored["analysis"]["analysis_metadata"]["raw_capture_loss_policy_reason"]
        == "raw_capture_queue_overflow_fatal"
    )
