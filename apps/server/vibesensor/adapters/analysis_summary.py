"""Adapter helpers for producing serialized analysis summaries at I/O edges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from vibesensor.domain import Finding as DomainFinding
from vibesensor.shared.boundaries.analysis_payloads import analysis_result_to_summary
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.diagnostics._analysis_models import FindingsBuilder
from vibesensor.use_cases.diagnostics._run_input import build_diagnostics_run_input
from vibesensor.use_cases.diagnostics._run_loader import _load_run as load_run
from vibesensor.use_cases.diagnostics.run_analysis import (
    RunAnalysis,
    build_findings_for_sensor_frames,
)


def summarize_sensor_frames(
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: FindingsBuilder | None = None,
) -> AnalysisSummary:
    """Analyze typed run data and serialize the explicit boundary summary payload."""
    run = build_diagnostics_run_input(metadata, samples, file_name=file_name)
    result = RunAnalysis(
        run,
        file_name=file_name,
        lang=lang,
        include_samples=include_samples,
        findings_builder=findings_builder,
    ).summarize()
    return analysis_result_to_summary(result)


def build_findings_for_samples(
    *,
    metadata: Mapping[str, object],
    samples: Sequence[Mapping[str, object]],
    lang: str | None = None,
    findings_builder: FindingsBuilder | None = None,
) -> tuple[DomainFinding, ...]:
    """Boundary helper that decodes raw payloads once before typed analysis."""

    return build_findings_for_sensor_frames(
        metadata=run_metadata_from_mapping(metadata),
        samples=sensor_frames_from_mappings(samples),
        lang=lang,
        findings_builder=findings_builder,
    )


def summarize_run_data(
    metadata: Mapping[str, object],
    samples: Sequence[Mapping[str, object]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: FindingsBuilder | None = None,
) -> AnalysisSummary:
    """Decode boundary payloads once, then execute the typed diagnostics core."""
    return summarize_sensor_frames(
        run_metadata_from_mapping(metadata),
        sensor_frames_from_mappings(samples),
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
    "build_findings_for_samples",
    "summarize_log",
    "summarize_run_data",
    "summarize_sensor_frames",
]
