"""Adapter helpers for producing serialized analysis summaries at I/O edges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from vibesensor.shared.boundaries.analysis_summary import analysis_result_to_summary
from vibesensor.shared.boundaries.sensor_frame_codec import (
    sensor_frames_from_rows,
    sensor_frames_to_json_objects,
)
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics._analysis_models import FindingsBuilder
from vibesensor.use_cases.diagnostics._context_decode import build_diagnostics_context
from vibesensor.use_cases.diagnostics._run_loader import _load_run as load_run
from vibesensor.use_cases.diagnostics.run_analysis import RunAnalysis


def summarize_run_data(
    metadata: JsonObject,
    samples: Sequence[Mapping[str, object]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: FindingsBuilder | None = None,
) -> AnalysisSummary:
    """Analyze pre-loaded run data and serialize the boundary summary payload."""
    context = build_diagnostics_context(metadata, file_name=file_name)
    typed_samples = sensor_frames_from_rows(samples)
    result = RunAnalysis(
        context,
        typed_samples,
        file_name=file_name,
        lang=lang,
        include_samples=include_samples,
        findings_builder=findings_builder,
    ).summarize()
    return analysis_result_to_summary(result)


def summarize_log(
    log_path: Path,
    lang: str | None = None,
    include_samples: bool = True,
    findings_builder: FindingsBuilder | None = None,
) -> AnalysisSummary:
    """Read a JSONL run file, analyse it, and serialize the boundary summary."""
    metadata, samples, _warnings = load_run(log_path)
    return summarize_run_data(
        metadata,
        sensor_frames_to_json_objects(samples),
        lang=lang,
        file_name=log_path.name,
        include_samples=include_samples,
        findings_builder=findings_builder,
    )


__all__ = [
    "analysis_result_to_summary",
    "summarize_log",
    "summarize_run_data",
]
