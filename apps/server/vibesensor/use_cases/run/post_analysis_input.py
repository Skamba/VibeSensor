"""Canonical typed post-analysis input shaping."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.use_cases.diagnostics._context import DiagnosticsContext
from vibesensor.use_cases.diagnostics._context_decode import build_diagnostics_context
from vibesensor.use_cases.diagnostics._types import Sample, normalize_analysis_samples

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
        samples=normalize_analysis_samples(loaded.samples),
        total_sample_count=loaded.total_sample_count,
        stride=loaded.stride,
    )
