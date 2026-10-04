"""Adapter helpers for producing serialized analysis summaries at I/O edges."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.analysis._run_input import build_diagnostics_run_input
from vibesensor.analysis.run_analysis import (
    RunAnalysis,
)
from vibesensor.analysis.summary_payload import analysis_result_to_summary
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.summary.contracts import AnalysisSummary


def summarize_sensor_frames(
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
) -> AnalysisSummary:
    """Analyze typed run data and serialize the explicit boundary summary payload."""
    run = build_diagnostics_run_input(metadata, samples, file_name=file_name)
    result = RunAnalysis(
        run,
        file_name=file_name,
        lang=lang,
        include_samples=include_samples,
    ).summarize()
    return analysis_result_to_summary(result)


__all__ = [
    "analysis_result_to_summary",
    "summarize_sensor_frames",
]
