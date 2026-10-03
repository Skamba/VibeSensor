"""Adapter helpers for producing serialized analysis summaries at I/O edges."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.analysis._run_input import build_diagnostics_run_input
from vibesensor.analysis.run_analysis import (
    RunAnalysis,
    build_findings_for_sensor_frames,
)
from vibesensor.analysis.summary_payload import analysis_result_to_summary
from vibesensor.domain.finding import Finding as DomainFinding
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
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


def build_findings_for_samples(
    *,
    metadata: Mapping[str, object],
    samples: Sequence[Mapping[str, object]],
    lang: str | None = None,
) -> tuple[DomainFinding, ...]:
    """Boundary helper that decodes raw payloads once before typed analysis."""

    return build_findings_for_sensor_frames(
        metadata=run_metadata_from_mapping(metadata),
        samples=sensor_frames_from_mappings(samples),
        lang=lang,
    )


def summarize_run_data(
    metadata: Mapping[str, object],
    samples: Sequence[Mapping[str, object]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
) -> AnalysisSummary:
    """Decode boundary payloads once, then execute the typed diagnostics core."""
    return summarize_sensor_frames(
        run_metadata_from_mapping(metadata),
        sensor_frames_from_mappings(samples),
        lang=lang,
        file_name=file_name,
        include_samples=include_samples,
    )


__all__ = [
    "analysis_result_to_summary",
    "build_findings_for_samples",
    "summarize_run_data",
    "summarize_sensor_frames",
]
