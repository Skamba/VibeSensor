"""Whole-run raw-window spectral executor and sidecar artifact builder."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol, cast

import numpy as np

from vibesensor.shared.constants.dsp import SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.shared.fft_analysis import SpectralAnalysisComputer, float_list, medfilt3
from vibesensor.shared.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.shared.types.raw_capture import (
    RawCaptureCoverageState,
    RawCaptureManifest,
    RawCaptureSensorManifest,
    RawCaptureSensorRange,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import (
    WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME,
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunWindowDescriptor,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import (
    WholeRunWindowPlan,
    plan_whole_run_windows,
)
from vibesensor.vibration_strength import StrengthPeak

DEFAULT_WHOLE_RUN_MAX_WORKERS = 1
_DEFAULT_CHUNK_WINDOW_COUNT = 32

__all__ = [
    "WholeRunSpectralArtifactBundle",
    "WholeRunWindowSpectralSummary",
    "build_whole_run_spectral_artifact_bundle",
    "whole_run_spectral_summaries_by_sensor",
    "whole_run_window_spectral_summaries_from_jsonl_bytes",
    "whole_run_window_spectral_summaries_to_jsonl_bytes",
]


class RawCaptureRangeLoader(Protocol):
    """Loader boundary for one sensor/sample range from raw sidecar storage."""

    def __call__(
        self,
        *,
        client_id: str,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None: ...


@dataclass(frozen=True, slots=True)
class WholeRunWindowSpectralSummary:
    """Compact per-window spectral facts persisted alongside dense spectrum matrices."""

    window_index: int
    coverage_state: RawCaptureCoverageState
    returned_sample_start: int | None
    returned_sample_count: int
    dominant_freq_hz: float | None = None
    vibration_strength_db: float | None = None
    strength_peak_amp_g: float | None = None
    strength_floor_amp_g: float | None = None
    strength_bucket: str | None = None
    top_peaks: tuple[StrengthPeak, ...] = ()

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "window_index": self.window_index,
            "coverage_state": self.coverage_state,
            "returned_sample_start": self.returned_sample_start,
            "returned_sample_count": self.returned_sample_count,
        }
        payload["top_peaks"] = [
            {
                "hz": float(peak["hz"]),
                "amp": float(peak["amp"]),
                "vibration_strength_db": float(peak["vibration_strength_db"]),
                "strength_bucket": peak["strength_bucket"],
            }
            for peak in self.top_peaks
            if peak["hz"] > 0 and peak["amp"] > 0
        ]
        if self.dominant_freq_hz is not None:
            payload["dominant_freq_hz"] = self.dominant_freq_hz
        if self.vibration_strength_db is not None:
            payload["vibration_strength_db"] = self.vibration_strength_db
        if self.strength_peak_amp_g is not None:
            payload["strength_peak_amp_g"] = self.strength_peak_amp_g
        if self.strength_floor_amp_g is not None:
            payload["strength_floor_amp_g"] = self.strength_floor_amp_g
        if self.strength_bucket is not None:
            payload["strength_bucket"] = self.strength_bucket
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunWindowSpectralSummary:
        top_peaks_raw = data.get("top_peaks")
        top_peaks: list[StrengthPeak] = []
        if isinstance(top_peaks_raw, list):
            for item in top_peaks_raw:
                if not is_json_object(item):
                    continue
                hz = _float_or_none(item.get("hz"))
                amp = _float_or_none(item.get("amp"))
                vibration_strength_db = _float_or_none(item.get("vibration_strength_db"))
                if hz is None or amp is None or vibration_strength_db is None:
                    continue
                top_peaks.append(
                    {
                        "hz": hz,
                        "amp": amp,
                        "vibration_strength_db": vibration_strength_db,
                        "strength_bucket": _text_or_none(item.get("strength_bucket")),
                    }
                )
        return cls(
            window_index=_int_or_default(data.get("window_index"), default=0),
            coverage_state=_coverage_state(data.get("coverage_state")),
            returned_sample_start=_int_or_none(data.get("returned_sample_start")),
            returned_sample_count=_int_or_default(data.get("returned_sample_count"), default=0),
            dominant_freq_hz=_float_or_none(data.get("dominant_freq_hz")),
            vibration_strength_db=_float_or_none(data.get("vibration_strength_db")),
            strength_peak_amp_g=_float_or_none(data.get("strength_peak_amp_g")),
            strength_floor_amp_g=_float_or_none(data.get("strength_floor_amp_g")),
            strength_bucket=_text_or_none(data.get("strength_bucket")),
            top_peaks=tuple(top_peaks),
        )


@dataclass(frozen=True, slots=True)
class WholeRunSpectralArtifactBundle:
    """In-memory whole-run artifact payload ready for sidecar persistence."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]


@dataclass(frozen=True, slots=True)
class _SpectralChunk:
    sensor_manifest: RawCaptureSensorManifest
    chunk_index: int
    sample_start: int
    sample_count: int
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
    raw_capture_manifest: RawCaptureManifest,
    load_sensor_range: RawCaptureRangeLoader,
    max_workers: int = DEFAULT_WHOLE_RUN_MAX_WORKERS,
    chunk_window_count: int = _DEFAULT_CHUNK_WINDOW_COUNT,
    created_at: str | None = None,
) -> WholeRunSpectralArtifactBundle | None:
    """Compute deterministic whole-run spectral artifacts from raw sidecars."""

    sensors = tuple(sorted(raw_capture_manifest.sensors, key=lambda sensor: sensor.client_id))
    if not sensors:
        return None
    run_total_sample_count = max(int(sensor.sample_count) for sensor in sensors)
    plan = plan_whole_run_windows(metadata=metadata, total_sample_count=run_total_sample_count)
    chunks = _build_chunks(sensors=sensors, plan=plan, chunk_window_count=chunk_window_count)
    chunk_results = _execute_chunks(
        chunks=chunks,
        metadata=metadata,
        load_sensor_range=load_sensor_range,
        max_workers=max_workers,
    )
    return _build_artifact_bundle(
        run_id=run_id,
        plan=plan,
        sensors=sensors,
        chunk_results=chunk_results,
        created_at=created_at or utc_now_iso(),
    )


def _build_chunks(
    *,
    sensors: Sequence[RawCaptureSensorManifest],
    plan: WholeRunWindowPlan,
    chunk_window_count: int,
) -> tuple[_SpectralChunk, ...]:
    normalized_chunk_size = max(1, int(chunk_window_count))
    chunks: list[_SpectralChunk] = []
    for sensor_manifest in sensors:
        windows = plan.windows
        for chunk_index, start in enumerate(range(0, len(windows), normalized_chunk_size)):
            chunk_windows = windows[start : start + normalized_chunk_size]
            if not chunk_windows:
                continue
            sample_start = chunk_windows[0].sample_start
            sample_end = chunk_windows[-1].sample_end
            chunks.append(
                _SpectralChunk(
                    sensor_manifest=sensor_manifest,
                    chunk_index=chunk_index,
                    sample_start=sample_start,
                    sample_count=sample_end - sample_start,
                    windows=chunk_windows,
                )
            )
    return tuple(chunks)


def _execute_chunks(
    *,
    chunks: Sequence[_SpectralChunk],
    metadata: RunMetadata,
    load_sensor_range: RawCaptureRangeLoader,
    max_workers: int,
) -> tuple[_SpectralChunkResult, ...]:
    if not chunks:
        return ()
    if max_workers <= 1 or len(chunks) <= 1:
        return tuple(
            _process_chunk(
                chunk=chunk,
                metadata=metadata,
                load_sensor_range=load_sensor_range,
            )
            for chunk in chunks
        )
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="vibesensor-whole-run",
    ) as pool:
        submitted = [
            pool.submit(
                _process_chunk,
                chunk=chunk,
                metadata=metadata,
                load_sensor_range=load_sensor_range,
            )
            for chunk in chunks
        ]
        return tuple(future.result() for future in submitted)


def _process_chunk(
    *,
    chunk: _SpectralChunk,
    metadata: RunMetadata,
    load_sensor_range: RawCaptureRangeLoader,
) -> _SpectralChunkResult:
    sensor_manifest = chunk.sensor_manifest
    fft_computer = _build_fft_computer(
        metadata=metadata,
        sample_rate_hz=sensor_manifest.sample_rate_hz,
    )
    freq_hz = tuple(float_list(fft_computer.fft_params(sensor_manifest.sample_rate_hz)[0]))
    spectrum_rows = np.zeros((len(chunk.windows), len(freq_hz)), dtype=np.float32)
    range_result = load_sensor_range(
        client_id=sensor_manifest.client_id,
        sample_start=chunk.sample_start,
        sample_count=chunk.sample_count,
    )
    if range_result is None:
        range_result = RawCaptureSensorRange.missing(
            client_id=sensor_manifest.client_id,
            requested_sample_start=chunk.sample_start,
            requested_sample_count=chunk.sample_count,
        )
    summaries = tuple(
        _build_window_summary(
            window=window,
            range_result=range_result,
            spectrum_rows=spectrum_rows,
            row_index=row_index,
            metadata=metadata,
            sensor_manifest=sensor_manifest,
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
    range_result: RawCaptureSensorRange,
    spectrum_rows: np.ndarray,
    row_index: int,
    metadata: RunMetadata,
    sensor_manifest: RawCaptureSensorManifest,
    fft_computer: SpectralAnalysisComputer,
) -> WholeRunWindowSpectralSummary:
    coverage_state, returned_sample_start, returned_sample_count = _window_coverage(
        window=window,
        range_result=range_result,
    )
    if coverage_state != "full" or returned_sample_start is None:
        return WholeRunWindowSpectralSummary(
            window_index=window.window_index,
            coverage_state=coverage_state,
            returned_sample_start=returned_sample_start,
            returned_sample_count=returned_sample_count,
        )
    range_start = range_result.returned_sample_start
    assert range_start is not None
    local_start = returned_sample_start - range_start
    local_end = local_start + returned_sample_count
    samples_i16 = range_result.samples_i16[local_start:local_end]
    if samples_i16.shape[0] != returned_sample_count:
        return WholeRunWindowSpectralSummary(
            window_index=window.window_index,
            coverage_state="partial",
            returned_sample_start=returned_sample_start,
            returned_sample_count=int(samples_i16.shape[0]),
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
    return WholeRunWindowSpectralSummary(
        window_index=window.window_index,
        coverage_state="full",
        returned_sample_start=returned_sample_start,
        returned_sample_count=returned_sample_count,
        dominant_freq_hz=dominant_freq_hz,
        vibration_strength_db=vibration_strength_db,
        strength_peak_amp_g=peak_amp_g,
        strength_floor_amp_g=floor_amp_g,
        strength_bucket=strength_bucket,
        top_peaks=top_peaks,
    )


def _window_coverage(
    *,
    window: WholeRunWindowDescriptor,
    range_result: RawCaptureSensorRange,
) -> tuple[RawCaptureCoverageState, int | None, int]:
    if range_result.coverage_state == "missing" or range_result.returned_sample_start is None:
        return "missing", None, 0
    available_start = range_result.returned_sample_start
    available_end = range_result.returned_sample_end or available_start
    overlap_start = max(window.sample_start, available_start)
    overlap_end = min(window.sample_end, available_end)
    if overlap_end <= overlap_start:
        return "empty", None, 0
    returned_count = overlap_end - overlap_start
    if overlap_start != window.sample_start or overlap_end != window.sample_end:
        return "partial", overlap_start, returned_count
    return "full", overlap_start, returned_count


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
    window_f32 = samples_i16.astype(np.float32, copy=True)
    if accel_scale_g_per_lsb is not None and accel_scale_g_per_lsb > 0:
        window_f32 *= np.float32(accel_scale_g_per_lsb)
    axes_by_time = medfilt3(window_f32.T)
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
    sensors: Sequence[RawCaptureSensorManifest],
    chunk_results: Sequence[_SpectralChunkResult],
    created_at: str,
) -> WholeRunSpectralArtifactBundle:
    results_by_sensor: dict[str, list[_SpectralChunkResult]] = defaultdict(list)
    for result in chunk_results:
        results_by_sensor[result.sensor_id].append(result)
    artifact_files: list[WholeRunArtifactFile] = []
    artifact_contents: dict[str, bytes] = {}
    for sensor_manifest in sensors:
        sensor_results = sorted(
            results_by_sensor.get(sensor_manifest.client_id, []),
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
            WholeRunWindowSpectralSummary(
                window_index=window.window_index,
                coverage_state="missing",
                returned_sample_start=None,
                returned_sample_count=0,
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


def _npy_bytes(array: np.ndarray) -> bytes:
    buffer = BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def whole_run_window_spectral_summaries_to_jsonl_bytes(
    summaries: Sequence[WholeRunWindowSpectralSummary],
) -> bytes:
    if not summaries:
        return b""
    lines = [safe_json_dumps(summary.to_json_object()).encode("utf-8") for summary in summaries]
    return b"\n".join(lines) + b"\n"


def whole_run_window_spectral_summaries_from_jsonl_bytes(
    payload: bytes,
) -> tuple[WholeRunWindowSpectralSummary, ...]:
    """Reconstruct persisted whole-run spectral summaries from sidecar JSONL bytes."""

    if not payload:
        return ()
    summaries: list[WholeRunWindowSpectralSummary] = []
    text = payload.decode("utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = safe_json_loads(line, context="whole-run spectral summaries")
        if not is_json_object(parsed):
            raise ValueError("whole-run spectral summary line must decode to a JSON object")
        summaries.append(WholeRunWindowSpectralSummary.from_mapping(parsed))
    return tuple(summaries)


def whole_run_spectral_summaries_by_sensor(
    *,
    manifest: WholeRunArtifactManifest,
    artifact_contents: Mapping[str, bytes],
) -> dict[str, tuple[WholeRunWindowSpectralSummary, ...]]:
    """Load deterministic whole-run spectral summary rows keyed by sensor id."""

    summaries_by_sensor: dict[str, tuple[WholeRunWindowSpectralSummary, ...]] = {}
    summary_artifacts = sorted(
        (
            artifact
            for artifact in manifest.artifacts
            if artifact.artifact_key.startswith("spectral-summary:")
        ),
        key=lambda artifact: (artifact.sensor_id or "", artifact.artifact_key),
    )
    for artifact in summary_artifacts:
        if artifact.sensor_id is None:
            raise ValueError("whole-run spectral summary artifacts require sensor_id for loading")
        payload = artifact_contents.get(artifact.artifact_key)
        if payload is None:
            raise ValueError(
                f"whole-run spectral summaries missing bytes for {artifact.artifact_key}"
            )
        summaries = whole_run_window_spectral_summaries_from_jsonl_bytes(payload)
        if len(summaries) != manifest.total_window_count:
            raise ValueError(
                "whole-run spectral summaries require one row per window "
                f"for {artifact.artifact_key}"
            )
        summaries_by_sensor[artifact.sensor_id] = summaries
    return summaries_by_sensor


def _float_or_none(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _int_or_default(value: object, *, default: int) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else default


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _coverage_state(value: object) -> RawCaptureCoverageState:
    if value in {"missing", "empty", "partial", "full"}:
        return cast(RawCaptureCoverageState, value)
    return "missing"


def _default_frequency_grid(*, sample_rate_hz: int, fft_n: int) -> np.ndarray:
    fft_computer = SpectralAnalysisComputer(
        fft_n=fft_n,
        spectrum_min_hz=SPECTRUM_MIN_HZ,
        spectrum_max_hz=SPECTRUM_MAX_HZ,
    )
    return np.asarray(fft_computer.fft_params(sample_rate_hz)[0], dtype=np.float32)
