"""Live spectrum payload formatting.

Pure functions that assemble the WebSocket ``spectra`` payload from client
buffers. :class:`~vibesensor.infra.processing.processor.SignalProcessor` calls
them while holding its buffer lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from vibesensor.infra.processing.models import (
    SpectrumAxisData,
)
from vibesensor.infra.processing.time_align import compute_overlap
from vibesensor.shared.fft_analysis import float_list
from vibesensor.shared.types.payload_types import (
    AlignmentInfoPayload,
    FrequencyWarningPayload,
    SpectraPayload,
    SpectrumSeriesPayload,
)

if TYPE_CHECKING:
    from vibesensor.infra.processing.buffers import ClientBuffer

_EMPTY_F32: np.ndarray = np.array([], dtype=np.float32)


def _axis_data_or_empty(
    latest_spectrum: dict[str, SpectrumAxisData],
    axis: str,
) -> SpectrumAxisData:
    return latest_spectrum.get(axis, {"freq": _EMPTY_F32, "amp": _EMPTY_F32})


def _build_spectrum_frame_fingerprint(
    buffers: dict[str, ClientBuffer],
    client_ids: list[str],
) -> str:
    parts: list[str] = []
    for client_id in sorted(dict.fromkeys(client_ids)):
        buf = buffers.get(client_id)
        if buf is None or not buf.latest_spectrum:
            continue
        parts.append(
            f"{client_id}:{buf.buffer_epoch}:{buf.reset_generation}:{buf.spectrum_generation}"
        )
    return "|".join(parts)


def build_spectrum_payload(buf: ClientBuffer) -> SpectrumSeriesPayload:
    """Build a per-client spectrum payload from the buffer's latest spectrum.

    Manages the ``cached_spectrum_payload`` / ``cached_spectrum_payload_generation``
    fields on *buf* for fast subsequent lookups.
    """
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


def build_multi_spectrum_payload(
    buffers: dict[str, ClientBuffer],
    client_ids: list[str],
    *,
    default_sample_rate_hz: int,
    waveform_seconds: int,
) -> SpectraPayload:
    """Build the combined multi-client spectrum payload with alignment metadata.

    *buffers* must already be locked by the caller. When all clients share the
    same frequency axis, a single top-level ``freq`` is emitted.
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
        elif client_freq is not shared_freq and (
            len(client_freq) != len(shared_freq)
            or not np.allclose(
                client_freq,
                shared_freq,
                rtol=0.0,
                atol=1e-6,
            )
        ):
            mismatch_ids.append(client_id)
        per_client_freq[client_id] = client_freq
        clients[client_id] = build_spectrum_payload(buf)

        time_range = buf.analysis_time_range(
            default_sample_rate_hz=default_sample_rate_hz,
            waveform_seconds=waveform_seconds,
        )
        if time_range is not None:
            ranges.append((client_id, time_range.start_s, time_range.end_s))
            if time_range.synced:
                any_synced = True
            else:
                all_synced = False

    # When all clients share the same frequency axis, emit a single
    # top-level "freq" and omit per-client "freq" to reduce payload size.
    shared_freq_list: list[float]
    if mismatch_ids:
        shared_freq_list = float_list(shared_freq) if shared_freq is not None else []
        mismatch_set = set(mismatch_ids)
        for cid in clients:
            clients[cid]["freq"] = (
                float_list(per_client_freq[cid]) if cid in mismatch_set else shared_freq_list
            )
        shared_freq_list = []
    else:
        shared_freq_list = float_list(shared_freq) if shared_freq is not None else []

    payload: SpectraPayload = {
        "frame_fingerprint": _build_spectrum_frame_fingerprint(buffers, client_ids),
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
