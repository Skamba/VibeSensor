"""Analysis execution and top-cause extraction helpers for tests."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from test_support.core import standard_metadata
from vibesensor.analysis._run_input import build_diagnostics_run_input
from vibesensor.analysis.orders.matching import MatchedWindows
from vibesensor.analysis.post_analysis_loader import StoredPeaksReader
from vibesensor.analysis.run_analysis import RunAnalysis
from vibesensor.analysis.summary_payload import analysis_result_to_summary
from vibesensor.domain.finding import speed_bin_label
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sample_columns import (
    SAMPLE_COLUMN_FIELDS,
    SampleColumns,
    optional_floats,
)
from vibesensor.recording.sample_peaks import SamplePeaks
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
from vibesensor.summary.contracts import AnalysisSummary


def sample_columns_of(samples: Sequence[SensorFrame]) -> SampleColumns:
    """*samples* as the post-analysis reads a run's samples (``SampleColumns``), spectra too."""
    columns = SampleColumns.from_fields(
        {field: [getattr(sample, field) for sample in samples] for field in SAMPLE_COLUMN_FIELDS}
    )
    columns.spectra[:] = [sample.spectrum for sample in samples]
    return columns


def sample_column_values(columns: SampleColumns) -> dict[str, list[object]]:
    """*columns*' samples field by field, as ``SensorFrame`` has them (None where none)."""
    sensors = [columns.sensors[code] for code in columns.sensor_of.tolist()]
    values: dict[str, list[object]] = {
        "location": [location for location, _name, _client_id in sensors],
        "client_name": [name for _location, name, _client_id in sensors],
        "client_id": [client_id for _location, _name, client_id in sensors],
        "speed_source": [columns.speed_sources[code] for code in columns.speed_source_of.tolist()],
        "engine_rpm_source": [
            columns.engine_rpm_sources[code] for code in columns.engine_rpm_source_of.tolist()
        ],
        "strength_bucket": [
            None if code < 0 else columns.strength_buckets[code]
            for code in columns.strength_bucket_of.tolist()
        ],
        "sample_rate_hz": columns.sample_rate_hz.tolist(),
        "frames_dropped_total": columns.frames_dropped_total.tolist(),
        "queue_overflow_drops": columns.queue_overflow_drops.tolist(),
    }
    for field in SAMPLE_COLUMN_FIELDS:
        if field not in values:
            values[field] = list(optional_floats(getattr(columns, field)))
    return values


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
        metadata, sample_columns_of(samples), sample_peaks_of(samples), file_name=file_name
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


def matched_windows(
    points: Sequence[OrderMatchObservation],
    floors: Sequence[float],
    *,
    locations: Sequence[str] = (),
    samples: Sequence[int] | None = None,
) -> MatchedWindows:
    """*points*, matched in *samples* (0, 1, ...) at window *floors*, as ``MatchedWindows``.

    Its sensors are *locations* and then the points' others, in the order they come.
    """
    sample = np.arange(len(points)) if samples is None else np.array(samples)
    sample_t_s: list[float | None] = [None] * (int(sample.max(initial=-1)) + 1)
    sample_speed_kmh = list(sample_t_s)
    for at, point in zip(sample.tolist(), points, strict=True):
        sample_t_s[at] = point.t_s
        sample_speed_kmh[at] = point.speed_kmh
    names = list(dict.fromkeys([*locations, *(point.location for point in points)]))
    phases = list(dict.fromkeys(point.phase for point in points))
    bins = [
        speed_bin_label(point.speed_kmh)
        if point.speed_kmh is not None and point.speed_kmh > 0
        else None
        for point in points
    ]
    speed_bins = list(dict.fromkeys(bins))

    def known(value: float | None) -> float:
        return math.nan if value is None else value

    return MatchedWindows(
        sample=sample.astype(np.intp),
        speed_kmh=np.array([known(point.speed_kmh) for point in points], dtype=np.float64),
        predicted_hz=np.array([point.predicted_hz for point in points], dtype=np.float64),
        matched_hz=np.array([point.matched_hz for point in points], dtype=np.float64),
        rel_error=np.array([point.rel_error for point in points], dtype=np.float64),
        amp=np.array([point.amp for point in points], dtype=np.float64),
        floor=np.array(floors, dtype=np.float64),
        location=np.array([names.index(point.location) for point in points], dtype=np.intp),
        phase=np.array([phases.index(point.phase) for point in points], dtype=np.intp),
        speed_bin=np.array([speed_bins.index(label) for label in bins], dtype=np.intp),
        heard=np.array([point.heard for point in points], dtype=np.bool_),
        locations=names,
        phases=phases,
        speed_bins=speed_bins,
        sample_t_s=sample_t_s,
        sample_speed_kmh=sample_speed_kmh,
    )
