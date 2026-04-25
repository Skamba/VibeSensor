from __future__ import annotations

from vibesensor.domain import RunStatus
from vibesensor.shared.types.run_lifecycle import derive_run_artifact_lifecycle
from vibesensor.shared.types.run_schema import RunRawCaptureFinalize


def test_derive_run_artifact_lifecycle_marks_recording_run_pending() -> None:
    lifecycle = derive_run_artifact_lifecycle(
        status=RunStatus.RECORDING,
        has_raw_capture_manifest=False,
        raw_capture_artifacts_present=False,
        has_whole_run_artifact_manifest=False,
        whole_run_artifacts_present=False,
        raw_capture_finalize=None,
        has_analysis=False,
        analysis_corrupt=False,
    )

    assert lifecycle.stage == "recording"
    assert lifecycle.raw_capture == "pending"
    assert lifecycle.whole_run_artifacts == "pending"
    assert lifecycle.post_analysis == "pending"
    assert lifecycle.report == "pending"


def test_derive_run_artifact_lifecycle_marks_ready_complete_run() -> None:
    lifecycle = derive_run_artifact_lifecycle(
        status=RunStatus.COMPLETE,
        has_raw_capture_manifest=False,
        raw_capture_artifacts_present=False,
        has_whole_run_artifact_manifest=False,
        whole_run_artifacts_present=False,
        raw_capture_finalize=RunRawCaptureFinalize(status="not_configured"),
        has_analysis=True,
        analysis_corrupt=False,
    )

    assert lifecycle.stage == "post_analysis_ready"
    assert lifecycle.raw_capture == "not_recorded"
    assert lifecycle.whole_run_artifacts == "not_recorded"
    assert lifecycle.post_analysis == "ready"
    assert lifecycle.report == "ready"


def test_derive_run_artifact_lifecycle_marks_missing_and_degraded_artifacts() -> None:
    lifecycle = derive_run_artifact_lifecycle(
        status=RunStatus.ERROR,
        has_raw_capture_manifest=True,
        raw_capture_artifacts_present=False,
        has_whole_run_artifact_manifest=False,
        whole_run_artifacts_present=False,
        raw_capture_finalize=RunRawCaptureFinalize(
            status="failed",
            queue_depth=2,
            error_summary="writer crashed",
        ),
        has_analysis=False,
        analysis_corrupt=False,
    )

    assert lifecycle.stage == "post_analysis_degraded"
    assert lifecycle.raw_capture == "missing"
    assert lifecycle.whole_run_artifacts == "degraded"
    assert lifecycle.post_analysis == "degraded"
    assert lifecycle.report == "degraded"
