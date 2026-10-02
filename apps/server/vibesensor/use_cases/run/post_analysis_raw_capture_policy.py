"""Raw-capture quality helpers for post-analysis whole-run stages."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.raw_capture_quality import (
    RawCaptureLossPolicyAssessment,
    assess_raw_capture_loss_policy,
)
from vibesensor.shared.types.raw_capture import RawCaptureManifest

from .post_analysis_loader import LoadedPostAnalysisRun


@dataclass(frozen=True, slots=True)
class WholeRunRawCapturePolicy:
    manifest: RawCaptureManifest | None
    loss_policy: RawCaptureLossPolicyAssessment

    @property
    def whole_run_allowed(self) -> bool:
        return not self.loss_policy.gate_whole_run

    @property
    def prerequisite_reason(self) -> str:
        return (
            self.loss_policy.reason if self.loss_policy.gate_whole_run else "missing_prerequisites"
        )

    def raw_capture_prerequisites_met(self) -> bool:
        return self.manifest is not None and self.whole_run_allowed

    def raw_capture_skip_reason(self) -> str:
        return "raw_capture_manifest_missing" if self.manifest is None else self.prerequisite_reason


def assess_whole_run_raw_capture_policy(
    loaded: LoadedPostAnalysisRun,
) -> WholeRunRawCapturePolicy:
    manifest = loaded.raw_capture_manifest or (
        loaded.raw_capture.manifest if loaded.raw_capture is not None else None
    )
    return WholeRunRawCapturePolicy(
        manifest=manifest,
        loss_policy=assess_raw_capture_loss_policy(manifest),
    )
