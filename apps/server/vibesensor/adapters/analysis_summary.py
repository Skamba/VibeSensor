"""Adapter helpers for producing serialized analysis summaries at I/O edges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from vibesensor.shared.boundaries.analysis_summary import analysis_result_to_summary
from vibesensor.shared.boundaries.sensor_frame_codec import sensor_frames_from_rows
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.diagnostics._analysis_models import FindingsBuilder
from vibesensor.use_cases.diagnostics._context_decode import build_diagnostics_context
from vibesensor.use_cases.diagnostics._run_loader import _load_run as load_run
from vibesensor.use_cases.diagnostics.run_analysis import RunAnalysis


def summarize_sensor_frames(
    metadata: Mapping[str, object],
    samples: Sequence[SensorFrame],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: FindingsBuilder | None = None,
) -> AnalysisSummary:
    """Analyze typed run data and serialize the explicit boundary summary payload."""
    context = build_diagnostics_context(metadata, file_name=file_name)
    result = RunAnalysis(
        context,
        samples,
        file_name=file_name,
        lang=lang,
        include_samples=include_samples,
        findings_builder=findings_builder,
    ).summarize()
    return analysis_result_to_summary(result)


def summarize_run_data(
    metadata: Mapping[str, object],
    samples: Sequence[Mapping[str, object]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: FindingsBuilder | None = None,
) -> AnalysisSummary:
    """Decode boundary sample rows once, then execute the typed diagnostics core."""
    return summarize_sensor_frames(
        metadata,
        sensor_frames_from_rows(samples),
        lang=lang,
        file_name=file_name,
        include_samples=include_samples,
        findings_builder=findings_builder,
    )


def summarize_log(
    log_path: Path,
    lang: str | None = None,
    include_samples: bool = True,
    findings_builder: FindingsBuilder | None = None,
) -> AnalysisSummary:
    """Read a JSONL run file, analyse it, and serialize the boundary summary."""
    metadata, samples, _warnings = load_run(log_path)
    return summarize_sensor_frames(
        metadata,
        samples,
        lang=lang,
        file_name=log_path.name,
        include_samples=include_samples,
        findings_builder=findings_builder,
    )


__all__ = [
    "analysis_result_to_summary",
    "summarize_log",
    "summarize_run_data",
    "summarize_sensor_frames",
]
