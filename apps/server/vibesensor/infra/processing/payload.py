"""Payload formatting for spectrum and multi-spectrum views.

Pure functions that assemble API/WebSocket payload dicts from
:class:`~vibesensor.infra.processing.buffers.ClientBuffer` state.  Called by
:class:`~vibesensor.infra.processing.processor.SignalProcessor` wrapper methods
that handle locking and buffer lookup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from vibesensor.infra.processing.fft import float_list
from vibesensor.infra.processing.models import SpectrumAxisData
from vibesensor.infra.processing.time_align import compute_overlap
from vibesensor.shared.types.payload_types import (
    AlignmentInfoPayload,
    FrequencyWarningPayload,
    SpectraPayload,
    SpectrumSeriesPayload,
)
from vibesensor.vibration_strength import empty_vibration_strength_metrics

if TYPE_CHECKING:
    from collections.abc import Callable

    from vibesensor.infra.processing.buffers import ClientBuffer

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
