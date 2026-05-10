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

    def spectra_prerequisites_met(self, *, raw_range_reader_available: bool) -> bool:
        return self.manifest is not None and raw_range_reader_available and self.whole_run_allowed

    def spectra_prerequisite_reason(self, *, raw_range_reader_available: bool) -> str:
        if self.manifest is None:
            return "raw_capture_manifest_missing"
        if not raw_range_reader_available:
            return "raw_capture_range_reader_missing"
        return self.prerequisite_reason

    def context_prerequisites_met(self) -> bool:
        return self.manifest is not None and self.whole_run_allowed

    def context_prerequisite_reason(self) -> str:
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
