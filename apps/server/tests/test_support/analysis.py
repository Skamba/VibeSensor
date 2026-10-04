"""Analysis execution and top-cause extraction helpers for tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from test_support.core import standard_metadata
from vibesensor.analysis.summarize import summarize_sensor_frames
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
from vibesensor.summary.contracts import AnalysisSummary


def summarize_mappings(
    metadata: Mapping[str, object],
    samples: Sequence[Mapping[str, object]],
    *,
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
) -> AnalysisSummary:
    """Decode JSON-shaped metadata and sample rows, then run the production summary."""
    return summarize_sensor_frames(
        run_metadata_from_mapping(metadata),
        sensor_frames_from_mappings(samples),
        lang=lang,
        file_name=file_name,
        include_samples=include_samples,
    )


def run_analysis(
    samples: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    **meta_overrides: Any,
) -> dict[str, Any]:
    """Run the full analysis pipeline on *samples* and return the summary."""
    meta = metadata or standard_metadata(**meta_overrides)
    return summarize_mappings(meta, samples, lang=meta.get("language", "en"))


def extract_top(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first top-cause dict from a summary, or None."""
    causes = summary.get("top_causes") or []
    return causes[0] if causes else None


def top_confidence(summary: dict[str, Any]) -> float:
    """Return the confidence (0–1) of the top cause, or 0.0 if none."""
    top = extract_top(summary)
    return float(top.get("confidence", 0.0)) if top else 0.0
