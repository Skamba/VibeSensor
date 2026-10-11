"""Canonical typed post-analysis input shaping."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vibesensor.analysis._run_input import (
    DiagnosticsRunInput,
    build_diagnostics_run_input,
)
from vibesensor.analysis.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.analysis.raw_capture_replay import (
    RawReplaySummary,
    RawReplayWindowCoverage,
    replay_raw_windows,
)
from vibesensor.dsp.strength_bands import bucket_for_strength
from vibesensor.dsp.vibration_strength import vibration_strength_db_scalar
from vibesensor.recording.raw_capture import RawCaptureManifest
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sample_columns import SampleColumns
from vibesensor.recording.sample_peaks import SamplePeaks


@dataclass(frozen=True, slots=True)
class PostAnalysisRunInput:
    """Typed post-analysis input built once at the storage boundary."""

    diagnostics_run: DiagnosticsRunInput
    language: str
    total_summary_row_count: int
    summary_duration_s: float | None
    stride: int
    sampling_method: str
    evenly_spaced_sample_count: int
    event_sample_count: int
    raw_capture_available: bool
    raw_backed_summary_row_count: int
    raw_min_sensor_sample_count: int | None
    raw_min_sensor_duration_s: float | None
    raw_replay: RawReplaySummary
    raw_replay_window_coverages: tuple[RawReplayWindowCoverage, ...] = field(default_factory=tuple)

    @property
    def run_id(self) -> str:
        return self.diagnostics_run.run_id

    @property
    def context(self) -> RunMetadata:
        return self.diagnostics_run.context

    @property
    def samples(self) -> SampleColumns:
        return self.diagnostics_run.samples


def build_post_analysis_input(loaded: LoadedPostAnalysisRun) -> PostAnalysisRunInput:
    """Normalize one loaded persisted run into canonical diagnostics input.

    The raw replay rebuilds the samples it can (in place, with their peaks);
    the others keep their stored strengths, and their stored peaks are read.
    """
    samples = loaded.samples
    replay_result = replay_raw_windows(
        samples=samples,
        metadata=loaded.metadata,
        raw_capture=loaded.raw_capture,
    )
    stored = np.flatnonzero(~replay_result.rebuilt)
    peaks = (
        replay_result.peaks.with_peaks_of(stored, loaded.stored_peaks(stored.tolist()))
        if stored.size
        else replay_result.peaks
    )
    raw_capture_manifest = (
        loaded.raw_capture_manifest
        if loaded.raw_capture_manifest is not None
        else (loaded.raw_capture.manifest if loaded.raw_capture is not None else None)
    )
    raw_min_sensor_sample_count, raw_min_sensor_duration_s = _raw_capture_min_sensor_metrics(
        raw_capture_manifest
    )
    _ensure_strength_metrics(samples, peaks)
    return PostAnalysisRunInput(
        diagnostics_run=build_diagnostics_run_input(
            loaded.metadata,
            samples,
            peaks,
            file_name=loaded.run_id,
            window_means=[coverage.mean_xyz for coverage in replay_result.window_coverages],
        ),
        language=loaded.language,
        total_summary_row_count=loaded.total_summary_row_count,
        summary_duration_s=loaded.summary_duration_s,
        stride=loaded.stride,
        sampling_method=loaded.sampling_method,
        evenly_spaced_sample_count=loaded.evenly_spaced_sample_count,
        event_sample_count=loaded.event_sample_count,
        raw_capture_available=replay_result.summary.raw_capture_available,
        raw_backed_summary_row_count=replay_result.summary.raw_backed_summary_row_count,
        raw_min_sensor_sample_count=raw_min_sensor_sample_count,
        raw_min_sensor_duration_s=raw_min_sensor_duration_s,
        raw_replay=replay_result.summary,
        raw_replay_window_coverages=replay_result.window_coverages,
    )


def _raw_capture_min_sensor_metrics(
    manifest: RawCaptureManifest | None,
) -> tuple[int | None, float | None]:
    if manifest is None:
        return None, None
    min_sensor_sample_count: int | None = None
    min_sensor_duration_s: float | None = None
    for sensor in manifest.sensors:
        sample_rate_hz = int(sensor.sample_rate_hz)
        if sample_rate_hz <= 0:
            continue
        sample_count = max(0, int(sensor.sample_count))
        duration_s = sample_count / float(sample_rate_hz)
        if min_sensor_sample_count is None or sample_count < min_sensor_sample_count:
            min_sensor_sample_count = sample_count
        if min_sensor_duration_s is None or duration_s < min_sensor_duration_s:
            min_sensor_duration_s = duration_s
    return min_sensor_sample_count, min_sensor_duration_s


def _ensure_strength_metrics(samples: SampleColumns, peaks: SamplePeaks) -> None:
    """Give each sample without a strength one from its peak (else its first peak) and floor."""
    first_peak_amps = peaks.first_amp()
    for row in np.flatnonzero(np.isnan(samples.vibration_strength_db)).tolist():
        peak_amp_g = float(samples.strength_peak_amp_g[row])
        first_peak_amp = float(first_peak_amps[row])
        # NaN (no peak amplitude, or a sample without peaks) is not over 0.
        if not peak_amp_g > 0 and first_peak_amp > 0:
            peak_amp_g = first_peak_amp
        floor_amp_g = float(samples.strength_floor_amp_g[row])
        if not (peak_amp_g > 0 and floor_amp_g > 0):
            continue
        vibration_strength_db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=peak_amp_g,
            floor_amp_g=floor_amp_g,
        )
        samples.vibration_strength_db[row] = vibration_strength_db
        if samples.strength_bucket_of[row] < 0:
            samples.set_strength_buckets([row], [bucket_for_strength(vibration_strength_db)])
