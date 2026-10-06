"""Run loading and bounded sampling for background post-analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

from vibesensor.recording.raw_capture import RawCaptureManifest, RawRunCapture
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB
    from vibesensor.history.sample_store import SampleSelectionColumns

_MAX_POST_ANALYSIS_SAMPLES = 12_000
_EVENT_PRESERVING_SAMPLING_METHOD = "event_preserving"


@dataclass(frozen=True, slots=True)
class LoadedPostAnalysisRun:
    run_id: str
    metadata: RunMetadata
    language: str
    samples: list[SensorFrame]
    total_summary_row_count: int
    stride: int
    summary_duration_s: float | None = None
    sampling_method: str = "full"
    evenly_spaced_sample_count: int = 0
    event_sample_count: int = 0
    raw_capture: RawRunCapture | None = None
    raw_capture_manifest: RawCaptureManifest | None = None


@dataclass(frozen=True, slots=True)
class MissingPostAnalysisMetadata:
    run_id: str
    error_message: str


@dataclass(frozen=True, slots=True)
class EmptyPostAnalysisSamples:
    run_id: str
    error_message: str


PostAnalysisLoadResult = (
    LoadedPostAnalysisRun | MissingPostAnalysisMetadata | EmptyPostAnalysisSamples
)


@dataclass(frozen=True, slots=True)
class _PostAnalysisRowSelection:
    indices: list[int]
    stride: int
    sampling_method: str = "full"
    evenly_spaced_sample_count: int = 0
    event_sample_count: int = 0


def _sample_stride(total_sample_count: int) -> int:
    """Return the minimum stride that keeps bounded post-analysis under the sample cap."""
    if total_sample_count <= _MAX_POST_ANALYSIS_SAMPLES:
        return 1
    return ceil(total_sample_count / _MAX_POST_ANALYSIS_SAMPLES)


def load_post_analysis_run(
    *,
    run_id: str,
    db: HistoryDB,
) -> PostAnalysisLoadResult:
    """Load a run's metadata, its analysed summary rows, and its raw capture.

    A light pass reads only the columns that pick rows; only the kept rows (at
    most ``_MAX_POST_ANALYSIS_SAMPLES``) are decoded into ``SensorFrame``s, so
    peak memory does not grow with the drive's length.
    """
    stored_run = db.get_run(run_id)
    if stored_run is None:
        return MissingPostAnalysisMetadata(
            run_id=run_id,
            error_message="Metadata not found or corrupt; cannot analyse",
        )
    metadata = stored_run.metadata
    total_summary_row_count = max(0, int(stored_run.sample_count))
    raw_capture_manifest = stored_run.raw_capture_manifest

    columns = db.run_sample_selection_columns(run_id)
    if total_summary_row_count <= 0:
        total_summary_row_count = len(columns)
    selection = _select_post_analysis_rows(columns)
    samples = db.load_run_samples_by_id(run_id, columns.row_id[selection.indices].tolist())
    if not samples:
        return EmptyPostAnalysisSamples(
            run_id=run_id,
            error_message="No samples collected during run",
        )
    summary_duration_s = _summary_duration_s(
        columns.t_s,
        total_summary_row_count=total_summary_row_count,
        feature_interval_s=metadata.feature_interval_s,
    )

    return LoadedPostAnalysisRun(
        run_id=run_id,
        metadata=metadata,
        language=metadata.language or "en",
        samples=samples,
        total_summary_row_count=total_summary_row_count,
        summary_duration_s=summary_duration_s,
        stride=selection.stride,
        sampling_method=selection.sampling_method,
        evenly_spaced_sample_count=selection.evenly_spaced_sample_count,
        event_sample_count=selection.event_sample_count,
        raw_capture=db.load_raw_capture(run_id),
        raw_capture_manifest=raw_capture_manifest,
    )


def _summary_duration_s(
    t_s: npt.NDArray[np.float64],
    *,
    total_summary_row_count: int,
    feature_interval_s: float | None,
) -> float | None:
    observed_timestamps = t_s[np.isfinite(t_s) & (t_s >= 0.0)]
    if observed_timestamps.size:
        if observed_timestamps.size == 1:
            observed_duration_s = float(observed_timestamps[0])
            if feature_interval_s is not None and feature_interval_s > 0:
                observed_duration_s = max(observed_duration_s, feature_interval_s)
            if observed_duration_s > 0:
                return observed_duration_s
        else:
            observed_duration_s = max(
                0.0, float(observed_timestamps.max()) - float(observed_timestamps.min())
            )
            if observed_duration_s > 0:
                return observed_duration_s
    if feature_interval_s is not None and feature_interval_s > 0 and total_summary_row_count > 0:
        return float(total_summary_row_count) * float(feature_interval_s)
    return None


def _select_post_analysis_rows(columns: SampleSelectionColumns) -> _PostAnalysisRowSelection:
    total_sample_count = len(columns)
    stride = _sample_stride(total_sample_count)
    if stride <= 1 or total_sample_count <= _MAX_POST_ANALYSIS_SAMPLES:
        return _PostAnalysisRowSelection(indices=list(range(total_sample_count)), stride=1)
    event_budget = max(1, _MAX_POST_ANALYSIS_SAMPLES // 3)
    evenly_spaced_budget = max(1, _MAX_POST_ANALYSIS_SAMPLES - event_budget)
    evenly_spaced_indices = set(
        _evenly_spaced_indices(total_sample_count, selection_count=evenly_spaced_budget)
    )
    event_indices = _event_preserving_indices(
        _event_scores(columns),
        bucket_count=event_budget,
        exclude=evenly_spaced_indices,
    )
    selected_indices = sorted(evenly_spaced_indices | set(event_indices))
    if len(selected_indices) < _MAX_POST_ANALYSIS_SAMPLES:
        for index in _evenly_spaced_indices(
            total_sample_count,
            selection_count=min(total_sample_count, _MAX_POST_ANALYSIS_SAMPLES * 3),
        ):
            if index in evenly_spaced_indices or index in event_indices:
                continue
            selected_indices.append(index)
            if len(selected_indices) >= _MAX_POST_ANALYSIS_SAMPLES:
                break
        selected_indices.sort()
    return _PostAnalysisRowSelection(
        indices=selected_indices[:_MAX_POST_ANALYSIS_SAMPLES],
        stride=stride,
        sampling_method=_EVENT_PRESERVING_SAMPLING_METHOD,
        evenly_spaced_sample_count=len(evenly_spaced_indices),
        event_sample_count=len(set(event_indices) - evenly_spaced_indices),
    )


def _evenly_spaced_indices(total_sample_count: int, *, selection_count: int) -> list[int]:
    if total_sample_count <= 0 or selection_count <= 0:
        return []
    if selection_count >= total_sample_count:
        return list(range(total_sample_count))
    if selection_count == 1:
        return [0]
    last_index = total_sample_count - 1
    return sorted(
        {
            min(last_index, round((last_index * step) / float(selection_count - 1)))
            for step in range(selection_count)
        }
    )


def _event_scores(columns: SampleSelectionColumns) -> list[tuple[float, float, float]]:
    """Per-row loudness ``(strength dB, peak amp, top peak amp)``; missing ranks lowest."""
    return list(
        zip(
            np.nan_to_num(columns.vibration_strength_db, nan=-np.inf).tolist(),
            np.nan_to_num(columns.strength_peak_amp_g, nan=-np.inf).tolist(),
            np.nan_to_num(columns.top_peak_amp_g, nan=-np.inf).tolist(),
            strict=True,
        )
    )


def _event_preserving_indices(
    scores: Sequence[tuple[float, float, float]],
    *,
    bucket_count: int,
    exclude: set[int],
) -> list[int]:
    if bucket_count <= 0:
        return []
    total_sample_count = len(scores)
    selected: list[int] = []
    for bucket_index in range(bucket_count):
        start = (bucket_index * total_sample_count) // bucket_count
        end = ((bucket_index + 1) * total_sample_count) // bucket_count
        best_index: int | None = None
        best_score: tuple[float, float, float] | None = None
        for sample_index in range(start, end):
            if sample_index in exclude:
                continue
            score = scores[sample_index]
            if best_score is None or score > best_score:
                best_index = sample_index
                best_score = score
        if best_index is not None:
            selected.append(best_index)
    return selected
