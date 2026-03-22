"""Payload formatting for processing-facing debug and spectrum views.

Pure functions that assemble API/WebSocket/debug payload dicts from
processing state. Called by :class:`~vibesensor.infra.processing.processor.SignalProcessor`
wrapper methods that handle locking and buffer lookup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import numpy as np

from vibesensor.infra.processing.fft import float_list
from vibesensor.infra.processing.models import (
    DebugSpectrumRequest,
    ProcessorConfig,
    SpectrumAxisData,
)
from vibesensor.infra.processing.time_align import compute_overlap
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.payload_types import (
    AlignmentInfoPayload,
    DebugSpectrumErrorPayload,
    DebugSpectrumPayload,
    DebugSpectrumStatsPayload,
    DebugSpectrumTopBinPayload,
    FrequencyWarningPayload,
    IntakeStatsPayload,
    SharedWindowPayload,
    SpectraPayload,
    SpectrumSeriesPayload,
    TimeAlignmentPayload,
    TimeAlignmentSensorPayload,
)
from vibesensor.vibration_strength import empty_vibration_strength_metrics

if TYPE_CHECKING:
    from collections.abc import Callable

    from vibesensor.infra.processing.buffers import ClientBuffer
    from vibesensor.infra.processing.compute import SignalMetricsComputer
    from vibesensor.infra.workers.worker_pool import WorkerPoolStats

_EMPTY_F32: np.ndarray = np.array([], dtype=np.float32)

EMPTY_SPECTRUM_PAYLOAD: SpectrumSeriesPayload = {
    "combined_spectrum_amp_g": [],
    "strength_metrics": empty_vibration_strength_metrics(),
}


def _empty_spectrum_payload() -> SpectrumSeriesPayload:
    return {
        "combined_spectrum_amp_g": [],
        "strength_metrics": empty_vibration_strength_metrics(),
    }


def _axis_data_or_empty(
    latest_spectrum: dict[str, SpectrumAxisData],
    axis: str,
) -> SpectrumAxisData:
    return latest_spectrum.get(axis, {"freq": _EMPTY_F32, "amp": _EMPTY_F32})


def build_spectrum_payload(buf: ClientBuffer) -> SpectrumSeriesPayload:
    """Build a per-client spectrum payload from the buffer's cached spectrum.

    Manages the ``cached_spectrum_payload`` / ``cached_spectrum_payload_generation``
    fields on *buf* for fast subsequent lookups.
    """
    if not buf.latest_spectrum:
        return _empty_spectrum_payload()
    if (
        buf.cached_spectrum_payload is not None
        and buf.cached_spectrum_payload_generation == buf.spectrum_generation
    ):
        return buf.cached_spectrum_payload
    combined_axis = _axis_data_or_empty(buf.latest_spectrum, "combined")
    payload: SpectrumSeriesPayload = {
        "combined_spectrum_amp_g": float_list(combined_axis["amp"]),
        "strength_metrics": buf.latest_strength_metrics,
    }
    buf.cached_spectrum_payload = payload
    buf.cached_spectrum_payload_generation = buf.spectrum_generation
    return payload


def build_debug_spectrum_payload(
    request: DebugSpectrumRequest,
    config: ProcessorConfig,
    metrics: SignalMetricsComputer,
) -> DebugSpectrumPayload | DebugSpectrumErrorPayload:
    """Build the route-facing debug spectrum payload from a copied FFT request."""
    if request.fft_block is None:
        return {
            "error": "insufficient samples",
            "count": request.count,
            "fft_n": config.fft_n,
        }

    fft_block = request.fft_block
    raw_mean = fft_block.mean(axis=1).tolist()
    raw_std = fft_block.std(axis=1).tolist()
    raw_min = fft_block.min(axis=1).tolist()
    raw_max = fft_block.max(axis=1).tolist()

    fft_result = metrics.compute_fft_spectrum(fft_block, request.sample_rate_hz)
    freq_slice = fft_result["freq_slice"]
    combined_amp = fft_result["combined_amp"]
    strength_metrics = fft_result["strength_metrics"]
    detrended_std = (fft_block - fft_block.mean(axis=1, keepdims=True)).std(axis=1).tolist()

    sorted_idx = np.argsort(combined_amp)[::-1]
    spectrum = fft_result["spectrum_by_axis"]
    top_bins: list[DebugSpectrumTopBinPayload] = []
    for index in sorted_idx[:10]:
        top_bins.append(
            {
                "bin": int(index),
                "freq_hz": float(freq_slice[index]),
                "combined_amp_g": float(combined_amp[index]),
                "x_amp_g": float(spectrum["x"]["amp"][index]),
                "y_amp_g": float(spectrum["y"]["amp"][index]),
                "z_amp_g": float(spectrum["z"]["amp"][index]),
            },
        )

    raw_stats: DebugSpectrumStatsPayload = {
        "mean_g": raw_mean,
        "std_g": raw_std,
        "min_g": raw_min,
        "max_g": raw_max,
    }
    return {
        "client_id": request.client_id,
        "sample_rate_hz": request.sample_rate_hz,
        "fft_n": config.fft_n,
        "fft_scale": metrics.fft_scale,
        "window": "hann",
        "spectrum_min_hz": config.spectrum_min_hz,
        "spectrum_max_hz": config.spectrum_max_hz,
        "freq_bins": len(freq_slice),
        "freq_resolution_hz": float(request.sample_rate_hz) / config.fft_n,
        "raw_stats": raw_stats,
        "detrended_std_g": detrended_std,
        "vibration_strength_db": float(strength_metrics.get("vibration_strength_db", 0)),
        "top_bins_by_amplitude": top_bins,
        "strength_peaks": list(strength_metrics.get("top_peaks", [])),
    }


def build_intake_stats_payload(
    base_stats: IntakeStatsPayload,
    worker_pool_stats: WorkerPoolStats | None,
) -> IntakeStatsPayload:
    """Build the health/debug intake stats payload."""
    payload: IntakeStatsPayload = dict(base_stats)
    if worker_pool_stats is not None:
        worker_pool_payload = cast(JsonObject, dict(worker_pool_stats))
        payload["worker_pool"] = worker_pool_payload
    return payload


def build_time_alignment_payload(
    buffers: dict[str, ClientBuffer],
    client_ids: list[str],
    analysis_time_range_fn: Callable[[ClientBuffer], tuple[float, float, bool] | None],
) -> TimeAlignmentPayload:
    """Build time-alignment info for the requested sensors from locked buffer state."""
    per_sensor: dict[str, TimeAlignmentSensorPayload] = {}
    ranges: list[tuple[float, float]] = []
    included: list[str] = []
    excluded: list[str] = []
    all_synced = True

    for client_id in client_ids:
        buf = buffers.get(client_id)
        if buf is None:
            excluded.append(client_id)
            continue
        time_range = analysis_time_range_fn(buf)
        if time_range is None:
            excluded.append(client_id)
            continue
        start, end, synced = time_range
        if not synced:
            all_synced = False
        per_sensor[client_id] = {
            "start_s": start,
            "end_s": end,
            "duration_s": end - start,
            "synced": synced,
        }
        ranges.append((start, end))
        included.append(client_id)

    if len(ranges) < 2:
        return {
            "per_sensor": per_sensor,
            "shared_window": None,
            "overlap_ratio": 1.0 if len(ranges) == 1 else 0.0,
            "aligned": True,
            "clock_synced": all_synced and bool(included),
            "sensors_included": included,
            "sensors_excluded": excluded,
        }

    overlap = compute_overlap([start for start, _ in ranges], [end for _, end in ranges])
    shared: SharedWindowPayload | None = None
    if overlap.overlap_s > 0:
        shared = {
            "start_s": overlap.shared_start,
            "end_s": overlap.shared_end,
            "duration_s": overlap.overlap_s,
        }

    return {
        "per_sensor": per_sensor,
        "shared_window": shared,
        "overlap_ratio": round(overlap.overlap_ratio, 4),
        "aligned": overlap.aligned,
        "clock_synced": all_synced,
        "sensors_included": included,
        "sensors_excluded": excluded,
    }


def build_multi_spectrum_payload(
    buffers: dict[str, ClientBuffer],
    client_ids: list[str],
    spectrum_fn: Callable[[str], SpectrumSeriesPayload],
    analysis_time_range_fn: Callable[[ClientBuffer], tuple[float, float, bool] | None],
) -> SpectraPayload:
    """Build a combined multi-client spectrum payload with alignment metadata.

    Parameters
    ----------
    buffers:
        Mapping of client ID → ClientBuffer (already under lock).
    client_ids:
        Client IDs to include.
    spectrum_fn:
        Callable to produce per-client spectrum (already under the same lock).
    analysis_time_range_fn:
        Callable to derive (start_s, end_s, synced) for a buffer.

    """
    shared_freq: np.ndarray | None = None
    clients: dict[str, SpectrumSeriesPayload] = {}
    mismatch_ids: list[str] = []
    per_client_freq: dict[str, np.ndarray] = {}

    ranges: list[tuple[str, float, float]] = []
    any_synced = False
    all_synced = True
    for client_id in client_ids:
        buf = buffers.get(client_id)
        if buf is None or not buf.latest_spectrum:
            continue
        client_freq = buf.latest_spectrum["x"]["freq"]
        if not isinstance(client_freq, np.ndarray):
            client_freq = np.array(client_freq, dtype=np.float32)
        if shared_freq is None:
            shared_freq = client_freq
        elif len(client_freq) != len(shared_freq) or not np.allclose(
            client_freq,
            shared_freq,
            rtol=0.0,
            atol=1e-6,
        ):
            mismatch_ids.append(client_id)
        per_client_freq[client_id] = client_freq
        clients[client_id] = spectrum_fn(client_id)

        tr = analysis_time_range_fn(buf)
        if tr is not None:
            ranges.append((client_id, tr[0], tr[1]))
            if tr[2]:
                any_synced = True
            else:
                all_synced = False

    # When all clients share the same frequency axis, emit a single
    # top-level "freq" and omit per-client "freq" to reduce payload size.
    if mismatch_ids:
        for cid, freq_arr in per_client_freq.items():
            clients[cid]["freq"] = float_list(freq_arr)
        shared_freq_list: list[float] = []
    else:
        shared_freq_list = float_list(shared_freq) if shared_freq is not None else []

    payload: SpectraPayload = {
        "freq": shared_freq_list,
        "clients": clients,
    }
    if mismatch_ids:
        warning: FrequencyWarningPayload = {
            "code": "frequency_bin_mismatch",
            "message": "Per-client frequency axes returned due to sample-rate mismatch.",
            "client_ids": sorted(mismatch_ids),
        }
        payload["warning"] = warning

    if len(ranges) >= 2:
        ov = compute_overlap(
            [s for _, s, _ in ranges],
            [e for _, _, e in ranges],
        )
        alignment: AlignmentInfoPayload = {
            "overlap_ratio": round(ov.overlap_ratio, 4),
            "aligned": ov.aligned,
            "shared_window_s": round(ov.overlap_s, 4),
            "sensor_count": len(ranges),
            "clock_synced": all_synced and any_synced,
        }
        payload["alignment"] = alignment
    return payload
