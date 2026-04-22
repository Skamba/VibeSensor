"""Canonical typed post-analysis input shaping."""

from __future__ import annotations

from dataclasses import dataclass, replace

from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.strength_bands import bucket_for_strength
from vibesensor.use_cases.diagnostics._run_input import (
    DiagnosticsRunInput,
    build_diagnostics_run_input,
)
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.vibration_strength import vibration_strength_db_scalar

from .post_analysis_loader import LoadedPostAnalysisRun
from .raw_capture_replay import build_raw_backed_samples


@dataclass(frozen=True, slots=True)
class PostAnalysisRunInput:
    """Typed post-analysis input built once at the storage boundary."""

    diagnostics_run: DiagnosticsRunInput
    language: str
    total_sample_count: int
    stride: int
    raw_capture_available: bool
    raw_backed_sample_count: int

    @property
    def run_id(self) -> str:
        return self.diagnostics_run.run_id

    @property
    def context(self) -> RunMetadata:
        return self.diagnostics_run.context

    @property
    def samples(self) -> tuple[Sample, ...]:
        return self.diagnostics_run.samples


def build_post_analysis_input(loaded: LoadedPostAnalysisRun) -> PostAnalysisRunInput:
    """Normalize one loaded persisted run into canonical diagnostics input."""

    replayed_samples, raw_backed_sample_count = build_raw_backed_samples(
        samples=tuple(loaded.samples),
        metadata=loaded.metadata,
        raw_capture=loaded.raw_capture,
    )
    samples = tuple(_ensure_strength_metrics(sample) for sample in replayed_samples)
    return PostAnalysisRunInput(
        diagnostics_run=build_diagnostics_run_input(
            loaded.metadata,
            samples,
            file_name=loaded.run_id,
        ),
        language=loaded.language,
        total_sample_count=loaded.total_sample_count,
        stride=loaded.stride,
        raw_capture_available=loaded.raw_capture is not None,
        raw_backed_sample_count=raw_backed_sample_count,
    )


def _ensure_strength_metrics(sample: Sample) -> Sample:
    if sample.vibration_strength_db is not None:
        return sample
    peak_amp_g = sample.strength_peak_amp_g
    if (peak_amp_g is None or peak_amp_g <= 0) and sample.top_peaks:
        first_peak_amp = sample.top_peaks[0].amp
        if first_peak_amp > 0:
            peak_amp_g = first_peak_amp
    floor_amp_g = sample.strength_floor_amp_g
    if peak_amp_g is None or peak_amp_g <= 0 or floor_amp_g is None or floor_amp_g <= 0:
        return sample
    vibration_strength_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak_amp_g,
        floor_amp_g=floor_amp_g,
    )
    strength_bucket = sample.strength_bucket or bucket_for_strength(vibration_strength_db)
    return replace(
        sample,
        vibration_strength_db=vibration_strength_db,
        strength_bucket=strength_bucket,
    )
