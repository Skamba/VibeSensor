"""Canonical typed post-analysis input shaping."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from vibesensor.shared.types.raw_capture import RawCaptureManifest
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.strength_bands import bucket_for_strength
from vibesensor.use_cases.diagnostics._run_input import (
    DiagnosticsRunInput,
    build_diagnostics_run_input,
)
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.vibration_strength import vibration_strength_db_scalar

from .post_analysis_loader import LoadedPostAnalysisRun
from .raw_capture_replay import RawReplaySummary, RawReplayWindowCoverage, build_raw_backed_samples


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
    context_samples: tuple[Sample, ...] = field(default_factory=tuple)

    @property
    def run_id(self) -> str:
        return self.diagnostics_run.run_id

    @property
    def context(self) -> RunMetadata:
        return self.diagnostics_run.context

    @property
    def samples(self) -> tuple[Sample, ...]:
        return self.diagnostics_run.samples


def build_post_analysis_input(loaded: LoadedPostAnalysisRun) -> PostAnalysisRunInput:
    """Normalize one loaded persisted run into canonical diagnostics input."""

    replay_result = build_raw_backed_samples(
        samples=tuple(loaded.samples),
        metadata=loaded.metadata,
        raw_capture=loaded.raw_capture,
    )
    raw_capture_manifest = (
        loaded.raw_capture_manifest
        if loaded.raw_capture_manifest is not None
        else (loaded.raw_capture.manifest if loaded.raw_capture is not None else None)
    )
    raw_min_sensor_sample_count, raw_min_sensor_duration_s = _raw_capture_min_sensor_metrics(
        raw_capture_manifest
    )
    samples = tuple(_ensure_strength_metrics(sample) for sample in replay_result.samples)
    return PostAnalysisRunInput(
        diagnostics_run=build_diagnostics_run_input(
            loaded.metadata,
            samples,
            file_name=loaded.run_id,
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
        context_samples=(
            tuple(loaded.context_samples) if loaded.context_samples is not None else tuple()
        ),
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


def _ensure_strength_metrics(sample: Sample) -> Sample:
    if sample.vibration_strength_db is not None:
        return sample
    peak_amp_g = sample.strength_peak_amp_g
    if (peak_amp_g is None or peak_amp_g <= 0) and sample.top_peaks:
        first_peak_amp = sample.top_peaks[0].amp
        if first_peak_amp > 0:
            peak_amp_g = first_peak_amp
    floor_amp_g = sample.strength_floor_amp_g
    if peak_amp_g is None or peak_amp_g <= 0 or floor_amp_g is None or floor_amp_g <= 0:
        return sample
    vibration_strength_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak_amp_g,
        floor_amp_g=floor_amp_g,
    )
    strength_bucket = sample.strength_bucket or bucket_for_strength(vibration_strength_db)
    return replace(
        sample,
        vibration_strength_db=vibration_strength_db,
        strength_bucket=strength_bucket,
    )
