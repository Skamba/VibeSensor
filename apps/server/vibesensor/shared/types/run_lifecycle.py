"""Canonical derived lifecycle model for persisted runs and artifact readiness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vibesensor.domain import RunStatus
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import RunRawCaptureFinalize

__all__ = [
    "ArtifactLifecycleState",
    "PostAnalysisLifecycleState",
    "ReportLifecycleState",
    "RunArtifactLifecycle",
    "RunLifecycleStage",
    "derive_run_artifact_lifecycle",
]

type RunLifecycleStage = Literal[
    "recording",
    "post_analysis_pending",
    "post_analysis_running",
    "post_analysis_ready",
    "post_analysis_degraded",
]
type ArtifactLifecycleState = Literal["not_recorded", "pending", "ready", "degraded", "missing"]
type PostAnalysisLifecycleState = Literal["pending", "running", "ready", "degraded"]
type ReportLifecycleState = Literal["pending", "ready", "degraded"]


@dataclass(frozen=True, slots=True)
class RunArtifactLifecycle:
    """Derived run stage plus explicit artifact/report readiness states."""

    stage: RunLifecycleStage
    raw_capture: ArtifactLifecycleState
    whole_run_artifacts: ArtifactLifecycleState
    post_analysis: PostAnalysisLifecycleState
    report: ReportLifecycleState

    def to_json_object(self) -> JsonObject:
        return {
            "stage": self.stage,
            "raw_capture": self.raw_capture,
            "whole_run_artifacts": self.whole_run_artifacts,
            "post_analysis": self.post_analysis,
            "report": self.report,
        }


def derive_run_artifact_lifecycle(
    *,
    status: RunStatus | str,
    has_raw_capture_manifest: bool,
    raw_capture_artifacts_present: bool,
    has_whole_run_artifact_manifest: bool,
    whole_run_artifacts_present: bool,
    raw_capture_finalize: RunRawCaptureFinalize | None,
    has_analysis: bool,
    analysis_corrupt: bool,
    post_analysis_running: bool = False,
) -> RunArtifactLifecycle:
    """Derive one canonical lifecycle object from persisted/runtime truth."""
    normalized_status = RunStatus(status)
    post_analysis = _derive_post_analysis_state(
        status=normalized_status,
        has_analysis=has_analysis,
        analysis_corrupt=analysis_corrupt,
        post_analysis_running=post_analysis_running,
    )
    return RunArtifactLifecycle(
        stage=_derive_stage(normalized_status, post_analysis),
        raw_capture=_derive_raw_capture_state(
            status=normalized_status,
            has_manifest=has_raw_capture_manifest,
            artifacts_present=raw_capture_artifacts_present,
            raw_capture_finalize=raw_capture_finalize,
        ),
        whole_run_artifacts=_derive_whole_run_artifact_state(
            has_manifest=has_whole_run_artifact_manifest,
            artifacts_present=whole_run_artifacts_present,
            post_analysis=post_analysis,
        ),
        post_analysis=post_analysis,
        report=_derive_report_state(post_analysis),
    )


def _derive_stage(
    status: RunStatus,
    post_analysis: PostAnalysisLifecycleState,
) -> RunLifecycleStage:
    if status == RunStatus.RECORDING:
        return "recording"
    if post_analysis == "running":
        return "post_analysis_running"
    if post_analysis == "ready":
        return "post_analysis_ready"
    if post_analysis == "degraded":
        return "post_analysis_degraded"
    return "post_analysis_pending"


def _derive_post_analysis_state(
    *,
    status: RunStatus,
    has_analysis: bool,
    analysis_corrupt: bool,
    post_analysis_running: bool,
) -> PostAnalysisLifecycleState:
    if has_analysis and not analysis_corrupt:
        return "ready"
    if status == RunStatus.RECORDING:
        return "pending"
    if status == RunStatus.ANALYZING:
        return "running" if post_analysis_running else "pending"
    return "degraded"


def _derive_raw_capture_state(
    *,
    status: RunStatus,
    has_manifest: bool,
    artifacts_present: bool,
    raw_capture_finalize: RunRawCaptureFinalize | None,
) -> ArtifactLifecycleState:
    if has_manifest:
        return "ready" if artifacts_present else "missing"
    if raw_capture_finalize is not None:
        if raw_capture_finalize.degraded:
            return "degraded"
        return "not_recorded"
    if status == RunStatus.RECORDING:
        return "pending"
    return "not_recorded"


def _derive_whole_run_artifact_state(
    *,
    has_manifest: bool,
    artifacts_present: bool,
    post_analysis: PostAnalysisLifecycleState,
) -> ArtifactLifecycleState:
    if has_manifest:
        return "ready" if artifacts_present else "missing"
    if post_analysis in {"pending", "running"}:
        return "pending"
    if post_analysis == "degraded":
        return "degraded"
    return "not_recorded"


def _derive_report_state(post_analysis: PostAnalysisLifecycleState) -> ReportLifecycleState:
    if post_analysis in {"pending", "running"}:
        return "pending"
    if post_analysis == "ready":
        return "ready"
    return "degraded"
