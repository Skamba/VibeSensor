"""Canonical typed post-analysis input shaping."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from vibesensor.strength_bands import bucket_for_strength
from vibesensor.use_cases.diagnostics._context import DiagnosticsContext
from vibesensor.use_cases.diagnostics._context_decode import build_diagnostics_context
from vibesensor.use_cases.diagnostics._types import (
    AnalysisSampleInput,
    Sample,
    normalize_analysis_samples,
)
from vibesensor.vibration_strength import vibration_strength_db_scalar

from .post_analysis_loader import LoadedPostAnalysisRun


@dataclass(frozen=True, slots=True)
class PostAnalysisRunInput:
    """Typed post-analysis input built once at the storage boundary."""

    run_id: str
    context: DiagnosticsContext
    language: str
    samples: list[Sample]
    total_sample_count: int
    stride: int


def build_post_analysis_input(loaded: LoadedPostAnalysisRun) -> PostAnalysisRunInput:
    """Normalize one loaded persisted run into canonical diagnostics input."""

    context = build_diagnostics_context(loaded.metadata.to_dict(), file_name=loaded.run_id)
    return PostAnalysisRunInput(
        run_id=loaded.run_id,
        context=context,
        language=loaded.language,
        samples=_normalize_post_analysis_samples(loaded.samples),
        total_sample_count=loaded.total_sample_count,
        stride=loaded.stride,
    )


def _normalize_post_analysis_samples(samples: Sequence[AnalysisSampleInput]) -> list[Sample]:
    rows = normalize_analysis_samples(samples)
    return [_ensure_strength_metrics(row) for row in rows]


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
