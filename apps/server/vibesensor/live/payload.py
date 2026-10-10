"""Live spectrum payload formatting.

Pure functions that assemble the WebSocket ``spectra`` payload from client
buffers. :class:`~vibesensor.live.processor.SignalProcessor` calls
them while holding its buffer lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from vibesensor.common.units import G_TO_MG
from vibesensor.dsp.fft_analysis import float_list
from vibesensor.dsp.window_spectrum import tone_line_level_g
from vibesensor.live.models import (
    SpectrumAxisData,
)
from vibesensor.live.payload_types import (
    SpectraPayload,
    SpectrumSeriesPayload,
)

if TYPE_CHECKING:
    from vibesensor.live.buffers import ClientBuffer

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
    freq = combined_axis["freq"]
    peak_mg = 0.0
    if freq.size > 1:
        # The level as the report reads it: a steady tone's peak, the axes as a vector.
        bin_hz = float(freq[1] - freq[0])
        peak_mg = (
            buf.latest_strength_metrics["peak_amp_g"] / tone_line_level_g(1.0, bin_hz) * G_TO_MG
        )
    payload: SpectrumSeriesPayload = {
        "combined_spectrum_amp_g": float_list(combined_axis["amp"]),
        "strength_metrics": buf.latest_strength_metrics,
        "peak_mg": peak_mg,
    }
    buf.cached_spectrum_payload = payload
    buf.cached_spectrum_payload_generation = buf.spectrum_generation
    return payload


def build_multi_spectrum_payload(
    buffers: dict[str, ClientBuffer],
    client_ids: list[str],
) -> SpectraPayload:
    """Build the combined multi-client spectrum payload.

    *buffers* must already be locked by the caller. When all clients share the
    same frequency axis, a single top-level ``freq`` is emitted.
    """
    shared_freq: np.ndarray | None = None
    clients: dict[str, SpectrumSeriesPayload] = {}
    mismatch_ids: list[str] = []
    per_client_freq: dict[str, np.ndarray] = {}

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

    return {
        "frame_fingerprint": _build_spectrum_frame_fingerprint(buffers, client_ids),
        "freq": shared_freq_list,
        "clients": clients,
    }
