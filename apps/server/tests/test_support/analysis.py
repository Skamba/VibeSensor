"""Analysis execution and top-cause extraction helpers for tests."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from test_support.core import standard_metadata
from vibesensor.analysis._run_input import build_diagnostics_run_input
from vibesensor.analysis.post_analysis_loader import StoredPeaksReader
from vibesensor.analysis.run_analysis import RunAnalysis
from vibesensor.analysis.summary_payload import analysis_result_to_summary
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sample_peaks import SamplePeaks
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
from vibesensor.summary.contracts import AnalysisSummary


def sample_peaks_of(samples: Sequence[SensorFrame]) -> SamplePeaks:
    """*samples*' ``top_peaks`` as the analysis reads a run's peaks (``SamplePeaks``)."""
    rows: list[int] = []
    hz: list[float] = []
    amp: list[float] = []
    local_floor_amp_g: list[float] = []
    for row, sample in enumerate(samples):
        for peak in sample.top_peaks:
            rows.append(row)
            hz.append(peak.hz)
            amp.append(peak.amp)
            local_floor_amp_g.append(
                math.nan if peak.local_floor_amp_g is None else peak.local_floor_amp_g
            )
    return SamplePeaks.of_peaks(rows, hz, amp, local_floor_amp_g, len(samples))


def peaks_by_sample(peaks: SamplePeaks) -> list[list[tuple[float, float, float | None]]]:
    """Each sample's peaks: frequency, amplitude and local floor (None where it has none)."""
    starts = peaks.start.tolist()
    rows = list(
        zip(
            peaks.hz.tolist(),
            peaks.amp.tolist(),
            [None if math.isnan(floor) else floor for floor in peaks.local_floor_amp_g.tolist()],
            strict=True,
        )
    )
    return [rows[start:end] for start, end in zip(starts[:-1], starts[1:], strict=True)]


def stored_peaks_of(samples: Sequence[SensorFrame]) -> StoredPeaksReader:
    """A ``LoadedPostAnalysisRun.stored_peaks`` that reads *samples*' ``top_peaks``."""
    return lambda positions: sample_peaks_of([samples[position] for position in positions])


def summarize_sensor_frames(
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
    lang: str | None = None,
    file_name: str = "run",
) -> AnalysisSummary:
    """Analyze typed run data and serialize the summary payload the way the app does."""
    run = build_diagnostics_run_input(
        metadata, samples, sample_peaks_of(samples), file_name=file_name
    )
    result = RunAnalysis(
        run,
        file_name=file_name,
        lang=lang,
    ).summarize()
    return analysis_result_to_summary(result)


def summarize_mappings(
    metadata: Mapping[str, object],
    samples: Sequence[Mapping[str, object]],
    *,
    lang: str | None = None,
    file_name: str = "run",
) -> AnalysisSummary:
    """Decode JSON-shaped metadata and sample rows, then run the production summary."""
    return summarize_sensor_frames(
        run_metadata_from_mapping(metadata),
        sensor_frames_from_mappings(samples),
        lang=lang,
        file_name=file_name,
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
