"""Whole-run raw-window spectral executor and sidecar artifact builder."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from io import BytesIO
from typing import cast

import numpy as np

from vibesensor.shared.constants.dsp import SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.shared.fft_analysis import SpectralAnalysisComputer, float_list
from vibesensor.shared.raw_capture_timeline import (
    RawSensorTimeline,
    assemble_raw_window_samples,
    build_raw_sensor_timeline,
    resolve_raw_window_end_time,
)
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.raw_capture import (
    RawCaptureCoverageState,
    RawCaptureLossStats,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import (
    WHOLE_RUN_ALGORITHM_VERSIONS,
    WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME,
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunSourceRawManifest,
    WholeRunWindowDescriptor,
    WholeRunWindowPolicy,
)
from vibesensor.shared.window_quality import score_window_quality
from vibesensor.use_cases.diagnostics.whole_run_spectral_projection import (
    WholeRunSpectralCoverageSummary,
    WholeRunWindowSpectralSummary,
    build_coverage_summary,
    whole_run_spectral_summaries_by_sensor,
    whole_run_window_spectral_summaries_from_jsonl_bytes,
    whole_run_window_spectral_summaries_to_jsonl_bytes,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import WholeRunWindowPlan
from vibesensor.vibration_strength import StrengthPeak

LOGGER = logging.getLogger(__name__)

DEFAULT_WHOLE_RUN_MAX_WORKERS = 1
_DEFAULT_CHUNK_WINDOW_COUNT = 32

__all__ = [
    "WholeRunSpectralArtifactBundle",
    "WholeRunSpectralBuildResult",
    "WholeRunSpectralCoverageSummary",
    "WholeRunWindowSpectralSummary",
    "build_whole_run_spectral_artifact_bundle",
    "whole_run_spectral_summaries_by_sensor",
    "whole_run_window_spectral_summaries_from_jsonl_bytes",
    "whole_run_window_spectral_summaries_to_jsonl_bytes",
]


@dataclass(frozen=True, slots=True)
class WholeRunSpectralArtifactBundle:
    """In-memory whole-run artifact payload ready for sidecar persistence."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]


@dataclass(frozen=True, slots=True)
class WholeRunSpectralBuildResult:
    """Whole-run spectral build outcome plus coverage/accounting metadata."""

    bundle: WholeRunSpectralArtifactBundle | None
    coverage_summary: WholeRunSpectralCoverageSummary
    window_plan: WholeRunWindowPlan | None = None


@dataclass(frozen=True, slots=True)
class _SpectralChunk:
    sensor_data: RawCaptureSensorData
    timeline: RawSensorTimeline
    loss_stats: RawCaptureLossStats
    chunk_index: int
    windows: tuple[WholeRunWindowDescriptor, ...]


@dataclass(frozen=True, slots=True)
class _SpectralChunkResult:
    sensor_id: str
    chunk_index: int
    freq_hz: tuple[float, ...]
    spectrum_rows: np.ndarray
    summaries: tuple[WholeRunWindowSpectralSummary, ...]


def build_whole_run_spectral_artifact_bundle(
    *,
    run_id: str,
    metadata: RunMetadata,
    raw_capture: RawRunCapture,
    max_workers: int = DEFAULT_WHOLE_RUN_MAX_WORKERS,
    chunk_window_count: int = _DEFAULT_CHUNK_WINDOW_COUNT,
    created_at: str | None = None,
) -> WholeRunSpectralBuildResult:
    """Compute deterministic time-aligned whole-run spectral artifacts from raw capture."""

    sensors = tuple(sorted(raw_capture.sensors, key=lambda sensor: sensor.manifest.client_id))
    if not sensors:
        coverage_summary = WholeRunSpectralCoverageSummary(
            total_sensor_window_count=0,
            full_sensor_window_count=0,
            partial_sensor_window_count=0,
            missing_sensor_window_count=0,
            empty_sensor_window_count=0,
            gap_count=0,
            overlap_count=0,
            dropped_chunk_count=0,
            late_packet_chunk_count=0,
            queue_overflow_chunk_count=0,
            invalid_chunk_count=0,
            write_error_chunk_count=0,
            sample_rate_mismatch_sensor_count=0,
            sample_rate_unverified_sensor_count=0,
            unanchored_sensor_count=0,
            legacy_sensor_count=0,
            sync_unverified_sensor_count=0,
            stale_sync_sensor_count=0,
            high_rtt_sensor_count=0,
            coverage_confidence="unavailable",
            udp_ingest_queue_drop_count=0,
        )
        return WholeRunSpectralBuildResult(bundle=None, coverage_summary=coverage_summary)
    timelines = {
        sensor.manifest.client_id: build_raw_sensor_timeline(
            raw_capture,
            sensor_id=sensor.manifest.client_id,
        )
        for sensor in sensors
    }
    plan = _build_time_domain_window_plan(metadata=metadata, timelines=timelines)
    if plan is None or plan.total_window_count <= 0:
        coverage_summary = build_coverage_summary(
            raw_capture=raw_capture,
            plan=None,
            sensors=sensors,
            timelines=timelines,
            summaries_by_sensor={},
        )
        return WholeRunSpectralBuildResult(
            bundle=None,
            coverage_summary=coverage_summary,
            window_plan=None,
        )
    chunks = _build_chunks(
        raw_capture=raw_capture,
        sensors=sensors,
        timelines=timelines,
        plan=plan,
        chunk_window_count=chunk_window_count,
    )
    chunk_results = _execute_chunks(
        chunks=chunks,
        metadata=metadata,
        max_workers=max_workers,
    )
    summaries_by_sensor = {
        sensor_id: tuple(summary for result in sensor_results for summary in result.summaries)
        for sensor_id, sensor_results in _chunk_results_by_sensor(chunk_results).items()
    }
    coverage_summary = build_coverage_summary(
        raw_capture=raw_capture,
        plan=plan,
        sensors=sensors,
        timelines=timelines,
        summaries_by_sensor=summaries_by_sensor,
    )
    return WholeRunSpectralBuildResult(
        bundle=_build_artifact_bundle(
            run_id=run_id,
            plan=plan,
            raw_capture=raw_capture,
            sensors=tuple(sensor.manifest for sensor in sensors),
            chunk_results=chunk_results,
            created_at=created_at or utc_now_iso(),
        ),
        coverage_summary=coverage_summary,
        window_plan=plan,
    )


def _build_time_domain_window_plan(
    *,
    metadata: RunMetadata,
    timelines: Mapping[str, RawSensorTimeline],
) -> WholeRunWindowPlan | None:
    fft_n = int(metadata.fft_window_size_samples or 0)
    feature_interval_s = float(metadata.feature_interval_s or 0.0)
    if fft_n <= 0 or feature_interval_s <= 0.0:
        return None
    aligned_timelines = tuple(
        timeline
        for timeline in timelines.values()
        if timeline.anchored and timeline.chunks and timeline.sample_rate_hz > 0
    )
    if not aligned_timelines:
        return None
    reference_sample_rate_hz = _reference_window_sample_rate_hz(
        metadata=metadata,
        timelines=aligned_timelines,
    )
    if reference_sample_rate_hz <= 0:
        return None
    stride_samples = max(1, int(round(feature_interval_s * float(reference_sample_rate_hz))))
    if stride_samples > fft_n:
        return None
    policy = WholeRunWindowPolicy(
        sample_rate_hz=reference_sample_rate_hz,
        window_size_samples=fft_n,
        stride_samples=stride_samples,
        overlap_samples=fft_n - stride_samples,
        feature_interval_s=feature_interval_s,
    )
    first_window_end_t_s = max(
        policy.window_duration_s,
        min(
            _timeline_first_window_end_t_s(timeline, window_size_samples=fft_n)
            for timeline in aligned_timelines
        ),
    )
    coverage_end_t_s = max(_timeline_end_t_s(timeline) for timeline in aligned_timelines)
    if coverage_end_t_s < first_window_end_t_s:
        return None
    windows = _build_time_windows(
        policy=policy,
        first_window_end_t_s=first_window_end_t_s,
        coverage_end_t_s=coverage_end_t_s,
    )
    if not windows:
        return None
    return WholeRunWindowPlan(
        policy=policy,
        coverage_sample_start=windows[0].sample_start,
        coverage_sample_end=windows[-1].sample_end,
        windows=windows,
    )


def _timeline_first_window_end_t_s(
    timeline: RawSensorTimeline,
    *,
    window_size_samples: int,
) -> float:
    if (
        not timeline.chunks
        or timeline.run_start_monotonic_us is None
        or timeline.sample_rate_hz <= 0
        or window_size_samples <= 0
    ):
        return 0.0
    start_offset_us = max(
        0.0,
        timeline.chunks[0].start_us - float(timeline.run_start_monotonic_us),
    )
    return (start_offset_us / 1_000_000.0) + (
        float(window_size_samples) / float(timeline.sample_rate_hz)
    )


def _timeline_end_t_s(
    timeline: RawSensorTimeline,
) -> float:
    if not timeline.chunks or timeline.run_start_monotonic_us is None:
        return 0.0
    end_offset_us = max(
        0.0,
        timeline.chunks[-1].end_us - float(timeline.run_start_monotonic_us),
    )
    return end_offset_us / 1_000_000.0


def _reference_window_sample_rate_hz(
    *,
    metadata: RunMetadata,
    timelines: Sequence[RawSensorTimeline],
) -> int:
    configured_rate_hz = int(metadata.raw_sample_rate_hz or 0)
    if configured_rate_hz > 0:
        return configured_rate_hz
    observed_rates_hz = sorted(
        {timeline.sample_rate_hz for timeline in timelines if timeline.sample_rate_hz > 0}
    )
    return observed_rates_hz[-1] if observed_rates_hz else 0


def _build_time_windows(
    *,
    policy: WholeRunWindowPolicy,
    first_window_end_t_s: float,
    coverage_end_t_s: float,
) -> tuple[WholeRunWindowDescriptor, ...]:
    windows: list[WholeRunWindowDescriptor] = []
    end_t_s = first_window_end_t_s
    window_duration_s = policy.window_duration_s
    sample_rate_hz = float(policy.sample_rate_hz)
    while end_t_s <= coverage_end_t_s + 1e-9:
        sample_end = max(0, int(round(end_t_s * sample_rate_hz)))
        sample_start = max(0, sample_end - policy.window_size_samples)
        windows.append(
            WholeRunWindowDescriptor(
                window_index=len(windows),
                sample_start=sample_start,
                sample_end=sample_end,
                center_sample=sample_start + (policy.window_size_samples // 2),
                start_t_s=end_t_s - window_duration_s,
                end_t_s=end_t_s,
                center_t_s=end_t_s - (window_duration_s / 2.0),
            )
        )
        end_t_s += policy.feature_interval_s
    return tuple(windows)


def _build_chunks(
    *,
    raw_capture: RawRunCapture,
    sensors: Sequence[RawCaptureSensorData],
    timelines: Mapping[str, RawSensorTimeline],
    plan: WholeRunWindowPlan,
    chunk_window_count: int,
) -> tuple[_SpectralChunk, ...]:
    normalized_chunk_size = max(1, int(chunk_window_count))
    chunks: list[_SpectralChunk] = []
    for sensor_data in sensors:
        windows = plan.windows
        timeline = timelines[sensor_data.manifest.client_id]
        sensor_loss = raw_capture.manifest.sensor_loss(sensor_data.manifest.client_id)
        loss_stats = sensor_loss.losses if sensor_loss is not None else RawCaptureLossStats()
        for chunk_index, start in enumerate(range(0, len(windows), normalized_chunk_size)):
            chunk_windows = windows[start : start + normalized_chunk_size]
            if not chunk_windows:
                continue
            chunks.append(
                _SpectralChunk(
                    sensor_data=sensor_data,
                    timeline=timeline,
                    loss_stats=loss_stats,
                    chunk_index=chunk_index,
                    windows=chunk_windows,
                )
            )
    return tuple(chunks)


def _execute_chunks(
    *,
    chunks: Sequence[_SpectralChunk],
    metadata: RunMetadata,
    max_workers: int,
) -> tuple[_SpectralChunkResult, ...]:
    if not chunks:
        return ()
    if max_workers <= 1 or len(chunks) <= 1:
        return tuple(
            _process_chunk(
                chunk=chunk,
                metadata=metadata,
            )
            for chunk in chunks
        )
    total_chunks = len(chunks)
    max_pending_chunks = min(total_chunks, max(1, int(max_workers)))
    ordered_results: list[_SpectralChunkResult | None] = [None] * total_chunks
    pending: dict[Future[_SpectralChunkResult], int] = {}
    next_chunk_position = 0
    completed_chunks = 0
    shutdown_wait = True
    LOGGER.info(
        "Starting whole-run spectral chunk executor for run %s with %s chunks",
        metadata.run_id,
        total_chunks,
        extra=log_extra(
            event="whole_run_spectral_chunk_executor_started",
            run_id=metadata.run_id,
            total_chunks=total_chunks,
            max_workers=max_pending_chunks,
        ),
    )
    pool = ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="vibesensor-whole-run",
    )
    try:
        while pending or next_chunk_position < total_chunks:
            while next_chunk_position < total_chunks and len(pending) < max_pending_chunks:
                pending[
                    pool.submit(
                        _process_chunk,
                        chunk=chunks[next_chunk_position],
                        metadata=metadata,
                    )
                ] = next_chunk_position
                next_chunk_position += 1
            if not pending:
                continue
            done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            batch_completed = 0
            for future in done:
                chunk_position = pending.pop(future)
                chunk = chunks[chunk_position]
                try:
                    ordered_results[chunk_position] = future.result()
                except Exception:
                    for pending_future in pending:
                        pending_future.cancel()
                    LOGGER.warning(
                        "Whole-run spectral chunk failed for run %s",
                        metadata.run_id,
                        extra=log_extra(
                            event="whole_run_spectral_chunk_failed",
                            run_id=metadata.run_id,
                            sensor_id=chunk.sensor_data.manifest.client_id,
                            chunk_index=chunk.chunk_index,
                            chunk_position=chunk_position,
                            completed_chunks=completed_chunks,
                            total_chunks=total_chunks,
                        ),
                        exc_info=True,
                    )
                    shutdown_wait = False
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise
                batch_completed += 1
            completed_chunks += batch_completed
            LOGGER.info(
                "Whole-run spectral chunk progress for run %s: %s/%s chunks complete",
                metadata.run_id,
                completed_chunks,
                total_chunks,
                extra=log_extra(
                    event="whole_run_spectral_chunk_progress",
                    run_id=metadata.run_id,
                    completed_chunks=completed_chunks,
                    batch_completed=batch_completed,
                    total_chunks=total_chunks,
                    active_chunks=len(pending),
                    queued_chunks=(total_chunks - next_chunk_position),
                ),
            )
        missing_results = [index for index, result in enumerate(ordered_results) if result is None]
        if missing_results:
            raise RuntimeError(
                "whole-run spectral executor completed without results for "
                f"chunk positions {missing_results}"
            )
        return tuple(cast(_SpectralChunkResult, result) for result in ordered_results)
    finally:
        if shutdown_wait:
            pool.shutdown(wait=True)


def _process_chunk(
    *,
    chunk: _SpectralChunk,
    metadata: RunMetadata,
) -> _SpectralChunkResult:
    sensor_manifest = chunk.sensor_data.manifest
    sample_rate_hz = int(sensor_manifest.sample_rate_hz or 0)
    fft_computer = _build_fft_computer(
        metadata=metadata,
        sample_rate_hz=sample_rate_hz,
    )
    freq_hz = tuple(float_list(fft_computer.fft_params(sample_rate_hz)[0]))
    spectrum_rows = np.zeros((len(chunk.windows), len(freq_hz)), dtype=np.float32)
    summaries = tuple(
        _build_window_summary(
            window=window,
            sensor_data=chunk.sensor_data,
            timeline=chunk.timeline,
            spectrum_rows=spectrum_rows,
            row_index=row_index,
            metadata=metadata,
            sensor_manifest=sensor_manifest,
            loss_stats=chunk.loss_stats,
            fft_computer=fft_computer,
        )
        for row_index, window in enumerate(chunk.windows)
    )
    return _SpectralChunkResult(
        sensor_id=sensor_manifest.client_id,
        chunk_index=chunk.chunk_index,
        freq_hz=freq_hz,
        spectrum_rows=spectrum_rows,
        summaries=summaries,
    )


def _build_window_summary(
    *,
    window: WholeRunWindowDescriptor,
    sensor_data: RawCaptureSensorData,
    timeline: RawSensorTimeline,
    spectrum_rows: np.ndarray,
    row_index: int,
    metadata: RunMetadata,
    sensor_manifest: RawCaptureSensorManifest,
    loss_stats: RawCaptureLossStats,
    fft_computer: SpectralAnalysisComputer,
) -> WholeRunWindowSpectralSummary:
    if int(sensor_manifest.sample_rate_hz or 0) <= 0:
        return _coverage_only_summary(
            window=window,
            coverage_state="missing",
            coverage_reason="sample_rate_missing",
            loss_stats=loss_stats,
        )
    if sensor_manifest.sample_rate_proof_state == "timing_inconsistent":
        return _coverage_only_summary(
            window=window,
            coverage_state="missing",
            coverage_reason="sample_rate_unverified",
            loss_stats=loss_stats,
        )
    requested_end_us = float(timeline.run_start_monotonic_us or 0) + (window.end_t_s * 1_000_000.0)
    resolved = resolve_raw_window_end_time(
        timeline=timeline,
        requested_end_us=requested_end_us,
        sample_count=window.sample_count,
    )
    if resolved.coverage_state != "complete":
        return _coverage_only_summary(
            window=window,
            coverage_state=_summary_coverage_state(resolved.coverage_state),
            coverage_reason=resolved.reason,
            loss_stats=loss_stats,
        )
    samples_i16 = np.asarray(
        assemble_raw_window_samples(
            sensor_data=sensor_data,
            segments=resolved.segments,
        ),
        dtype=np.int16,
    )
    returned_sample_count = int(samples_i16.shape[0])
    if returned_sample_count != window.sample_count:
        return _coverage_only_summary(
            window=window,
            coverage_state="partial",
            coverage_reason="assembled_window_short",
            loss_stats=loss_stats,
            returned_sample_start=(
                resolved.segments[0].sample_start if resolved.segments else None
            ),
            returned_sample_count=returned_sample_count,
        )
    spectrum_row, top_peaks, vibration_strength_db, peak_amp_g, floor_amp_g, strength_bucket = (
        _compute_window_spectrum(
            samples_i16=samples_i16,
            sample_rate_hz=sensor_manifest.sample_rate_hz,
            accel_scale_g_per_lsb=metadata.accel_scale_g_per_lsb,
            fft_computer=fft_computer,
        )
    )
    spectrum_rows[row_index, :] = spectrum_row
    dominant_freq_hz = top_peaks[0]["hz"] if top_peaks else None
    returned_sample_start = resolved.segments[0].sample_start if resolved.segments else None
    returned_sample_count = sum(
        max(0, segment.sample_end - segment.sample_start) for segment in resolved.segments
    )
    return WholeRunWindowSpectralSummary(
        window_index=window.window_index,
        coverage_state="full",
        returned_sample_start=returned_sample_start,
        returned_sample_count=returned_sample_count,
        window_start_t_s=window.start_t_s,
        window_end_t_s=window.end_t_s,
        dominant_freq_hz=dominant_freq_hz,
        vibration_strength_db=vibration_strength_db,
        strength_peak_amp_g=peak_amp_g,
        strength_floor_amp_g=floor_amp_g,
        strength_bucket=strength_bucket,
        top_peaks=top_peaks,
        window_quality=score_window_quality(
            expected_sample_count=window.sample_count,
            returned_sample_count=returned_sample_count,
            coverage_state="full",
            samples_i16=samples_i16,
            samples_g=_scale_samples_to_g(
                samples_i16=samples_i16,
                accel_scale_g_per_lsb=metadata.accel_scale_g_per_lsb,
            ),
            sample_rate_hz=sensor_manifest.sample_rate_hz,
            peak_amp_g=peak_amp_g,
            noise_floor_amp_g=floor_amp_g,
            late_packet_chunk_count=loss_stats.late_packet_chunk_count,
            server_queue_drop_count=_server_queue_drop_count(loss_stats),
        ),
    )


def _coverage_only_summary(
    *,
    window: WholeRunWindowDescriptor,
    coverage_state: RawCaptureCoverageState,
    coverage_reason: str | None,
    loss_stats: RawCaptureLossStats | None = None,
    returned_sample_start: int | None = None,
    returned_sample_count: int = 0,
) -> WholeRunWindowSpectralSummary:
    loss_stats = loss_stats or RawCaptureLossStats()
    return WholeRunWindowSpectralSummary(
        window_index=window.window_index,
        coverage_state=coverage_state,
        returned_sample_start=returned_sample_start,
        returned_sample_count=returned_sample_count,
        window_start_t_s=window.start_t_s,
        window_end_t_s=window.end_t_s,
        coverage_reason=coverage_reason,
        window_quality=score_window_quality(
            expected_sample_count=window.sample_count,
            returned_sample_count=returned_sample_count,
            coverage_state=coverage_state,
            coverage_reason=coverage_reason,
            late_packet_chunk_count=loss_stats.late_packet_chunk_count,
            server_queue_drop_count=_server_queue_drop_count(loss_stats),
        ),
    )


def _server_queue_drop_count(loss_stats: RawCaptureLossStats) -> int:
    return (
        max(0, loss_stats.udp_ingest_queue_drop_count)
        + max(0, loss_stats.queue_overflow_chunk_count)
        + max(0, loss_stats.invalid_chunk_count)
        + max(0, loss_stats.write_error_chunk_count)
    )


def _summary_coverage_state(value: str) -> RawCaptureCoverageState:
    if value == "complete":
        return "full"
    if value == "partial":
        return "partial"
    return "missing"


def _compute_window_spectrum(
    *,
    samples_i16: np.ndarray,
    sample_rate_hz: int,
    accel_scale_g_per_lsb: float | None,
    fft_computer: SpectralAnalysisComputer,
) -> tuple[
    np.ndarray,
    tuple[StrengthPeak, ...],
    float | None,
    float | None,
    float | None,
    str | None,
]:
    window_f32 = _scale_samples_to_g(
        samples_i16=samples_i16,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
    )
    axes_by_time = window_f32.T
    detrended = axes_by_time - np.mean(axes_by_time, axis=1, keepdims=True)
    fft_result = fft_computer.compute_fft_spectrum(
        detrended,
        sample_rate_hz,
        spike_filter_enabled=False,
    )
    strength_metrics = fft_result["strength_metrics"]
    top_peaks = tuple(
        peak for peak in strength_metrics["top_peaks"] if peak["hz"] > 0 and peak["amp"] > 0
    )
    return (
        np.asarray(fft_result["combined_amp"], dtype=np.float32, copy=True),
        top_peaks,
        _float_or_none(strength_metrics.get("vibration_strength_db")),
        _float_or_none(strength_metrics.get("peak_amp_g")),
        _float_or_none(strength_metrics.get("noise_floor_amp_g")),
        strength_metrics.get("strength_bucket"),
    )


def _scale_samples_to_g(
    *,
    samples_i16: np.ndarray,
    accel_scale_g_per_lsb: float | None,
) -> np.ndarray:
    window_f32 = samples_i16.astype(np.float32, copy=True)
    if accel_scale_g_per_lsb is not None and accel_scale_g_per_lsb > 0:
        window_f32 *= np.float32(accel_scale_g_per_lsb)
    return window_f32


def _build_fft_computer(
    *,
    metadata: RunMetadata,
    sample_rate_hz: int,
) -> SpectralAnalysisComputer:
    return SpectralAnalysisComputer(
        fft_n=int(metadata.fft_window_size_samples or 0),
        spectrum_min_hz=SPECTRUM_MIN_HZ,
        spectrum_max_hz=SPECTRUM_MAX_HZ,
    )


def _build_artifact_bundle(
    *,
    run_id: str,
    plan: WholeRunWindowPlan,
    raw_capture: RawRunCapture,
    sensors: Sequence[RawCaptureSensorManifest],
    chunk_results: Sequence[_SpectralChunkResult],
    created_at: str,
) -> WholeRunSpectralArtifactBundle:
    results_by_sensor = _chunk_results_by_sensor(chunk_results)
    artifact_files: list[WholeRunArtifactFile] = []
    artifact_contents: dict[str, bytes] = {}
    for sensor_manifest in sensors:
        sensor_results = sorted(
            results_by_sensor.get(sensor_manifest.client_id, ()),
            key=lambda result: result.chunk_index,
        )
        freq_hz, spectrum_rows, summaries = _merge_sensor_results(
            sensor_manifest=sensor_manifest,
            plan=plan,
            sensor_results=sensor_results,
        )
        freq_artifact_key = f"spectral-grid:{sensor_manifest.client_id}"
        matrix_artifact_key = f"spectral-matrix:{sensor_manifest.client_id}"
        summary_artifact_key = f"spectral-summary:{sensor_manifest.client_id}"
        artifact_files.extend(
            [
                WholeRunArtifactFile(
                    artifact_key=freq_artifact_key,
                    relative_path=f"spectra/{sensor_manifest.client_id}/freq.f32.npy",
                    file_format="npy-f32-vector",
                    record_count=int(freq_hz.shape[0]),
                    sensor_id=sensor_manifest.client_id,
                ),
                WholeRunArtifactFile(
                    artifact_key=matrix_artifact_key,
                    relative_path=f"spectra/{sensor_manifest.client_id}/combined_spectrum.f32.npy",
                    file_format="npy-f32-matrix",
                    record_count=int(spectrum_rows.shape[0]),
                    sensor_id=sensor_manifest.client_id,
                ),
                WholeRunArtifactFile(
                    artifact_key=summary_artifact_key,
                    relative_path=f"spectra/{sensor_manifest.client_id}/windows.jsonl",
                    file_format="jsonl",
                    record_count=len(summaries),
                    sensor_id=sensor_manifest.client_id,
                ),
            ]
        )
        artifact_contents[freq_artifact_key] = _npy_bytes(freq_hz)
        artifact_contents[matrix_artifact_key] = _npy_bytes(spectrum_rows)
        artifact_contents[summary_artifact_key] = (
            whole_run_window_spectral_summaries_to_jsonl_bytes(summaries)
        )
    manifest = WholeRunArtifactManifest(
        run_id=run_id,
        relative_dir=f"{WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME}/{run_id}",
        window_policy=plan.policy,
        total_window_count=plan.total_window_count,
        artifacts=tuple(artifact_files),
        created_at=created_at,
        algorithm_versions=dict(WHOLE_RUN_ALGORITHM_VERSIONS),
        configuration={
            "sample_rate_hz": plan.policy.sample_rate_hz,
            "window_size_samples": plan.policy.window_size_samples,
            "stride_samples": plan.policy.stride_samples,
            "overlap_samples": plan.policy.overlap_samples,
            "feature_interval_s": plan.policy.feature_interval_s,
            "spectrum_min_hz": SPECTRUM_MIN_HZ,
            "spectrum_max_hz": SPECTRUM_MAX_HZ,
            "sensor_count": len(sensors),
            "spectrum_storage_format": "npy-f32",
            "summary_storage_format": "jsonl",
        },
        source_raw_manifests=(
            WholeRunSourceRawManifest.from_raw_capture_manifest(raw_capture.manifest),
        ),
    )
    return WholeRunSpectralArtifactBundle(
        manifest=manifest,
        artifact_contents=artifact_contents,
    )


def _merge_sensor_results(
    *,
    sensor_manifest: RawCaptureSensorManifest,
    plan: WholeRunWindowPlan,
    sensor_results: Sequence[_SpectralChunkResult],
) -> tuple[np.ndarray, np.ndarray, tuple[WholeRunWindowSpectralSummary, ...]]:
    default_freq_hz = _default_frequency_grid(
        sample_rate_hz=sensor_manifest.sample_rate_hz,
        fft_n=plan.policy.window_size_samples,
    )
    if not sensor_results:
        empty_summaries = tuple(
            _coverage_only_summary(
                window=window,
                coverage_state="missing",
                coverage_reason="sensor_missing",
            )
            for window in plan.windows
        )
        return (
            default_freq_hz,
            np.zeros((plan.total_window_count, default_freq_hz.shape[0]), dtype=np.float32),
            empty_summaries,
        )
    merged_freq_hz = np.asarray(sensor_results[0].freq_hz, dtype=np.float32)
    summary_list: list[WholeRunWindowSpectralSummary] = []
    row_blocks: list[np.ndarray] = []
    for result in sensor_results:
        current_freq_hz = np.asarray(result.freq_hz, dtype=np.float32)
        if current_freq_hz.shape != merged_freq_hz.shape or not np.array_equal(
            current_freq_hz,
            merged_freq_hz,
        ):
            raise ValueError(
                "whole-run spectral executor produced inconsistent "
                f"frequency grids for {sensor_manifest.client_id}"
            )
        summary_list.extend(result.summaries)
        row_blocks.append(result.spectrum_rows)
    spectrum_rows = (
        np.vstack(row_blocks)
        if row_blocks
        else np.zeros((plan.total_window_count, merged_freq_hz.shape[0]), dtype=np.float32)
    )
    return merged_freq_hz, spectrum_rows, tuple(summary_list)


def _chunk_results_by_sensor(
    chunk_results: Sequence[_SpectralChunkResult],
) -> dict[str, list[_SpectralChunkResult]]:
    results_by_sensor: dict[str, list[_SpectralChunkResult]] = defaultdict(list)
    for result in chunk_results:
        results_by_sensor[result.sensor_id].append(result)
    return results_by_sensor


def _default_frequency_grid(*, sample_rate_hz: int, fft_n: int) -> np.ndarray:
    fft_computer = SpectralAnalysisComputer(
        fft_n=fft_n,
        spectrum_min_hz=SPECTRUM_MIN_HZ,
        spectrum_max_hz=SPECTRUM_MAX_HZ,
    )
    return np.asarray(float_list(fft_computer.fft_params(sample_rate_hz)[0]), dtype=np.float32)


def _npy_bytes(array: np.ndarray) -> bytes:
    buffer = BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
