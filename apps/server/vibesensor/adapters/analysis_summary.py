"""Adapter helpers for producing serialized analysis summaries at I/O edges."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from vibesensor.domain import Finding as DomainFinding
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.boundaries.analysis_summary import (
    AnalysisResultLike,
    analysis_result_to_summary,
)
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics import RunAnalysis
from vibesensor.use_cases.diagnostics.helpers import _load_run


def summarize_run_data(
    metadata: JsonObject,
    samples: list[JsonObject],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> AnalysisSummary:
    """Analyze pre-loaded run data and serialize the boundary summary payload."""
    result = RunAnalysis(
        metadata,
        samples,
        file_name=file_name,
        lang=lang,
        include_samples=include_samples,
        findings_builder=findings_builder,
    ).summarize()
    return analysis_result_to_summary(cast(AnalysisResultLike, result))


def summarize_log(
    log_path: Path,
    lang: str | None = None,
    include_samples: bool = True,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> AnalysisSummary:
    """Read a JSONL run file, analyse it, and serialize the boundary summary."""
    metadata, samples, _warnings = _load_run(log_path)
    return summarize_run_data(
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
]
