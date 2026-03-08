"""Payload formatting for spectrum, multi-spectrum, and selected-client views.

Pure functions that assemble API/WebSocket payload dicts from
:class:`~vibesensor.processing.buffers.ClientBuffer` state.  Called by
:class:`~vibesensor.processing.processor.SignalProcessor` wrapper methods
that handle locking and buffer lookup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ..payload_types import (
    AlignmentInfoPayload,
    FrequencyWarningPayload,
    SelectedClientPayload,
    SelectedSpectrumPayload,
    SpectraPayload,
    SpectrumSeriesPayload,
    WaveformPayload,
)
from .fft import AXES, float_list
from .models import SpectrumAxisData
from .time_align import compute_overlap

if TYPE_CHECKING:
    from collections.abc import Callable

    from .buffers import ClientBuffer

_EMPTY_F32: np.ndarray = np.array([], dtype=np.float32)

EMPTY_SPECTRUM_PAYLOAD: SpectrumSeriesPayload = {
    "x": [],
    "y": [],
    "z": [],
    "combined_spectrum_amp_g": [],
    "strength_metrics": {},
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
        return dict(EMPTY_SPECTRUM_PAYLOAD)
    if (
        buf.cached_spectrum_payload is not None
        and buf.cached_spectrum_payload_generation == buf.spectrum_generation
    ):
        return buf.cached_spectrum_payload
    x_axis = _axis_data_or_empty(buf.latest_spectrum, "x")
    y_axis = _axis_data_or_empty(buf.latest_spectrum, "y")
    z_axis = _axis_data_or_empty(buf.latest_spectrum, "z")
    combined_axis = _axis_data_or_empty(buf.latest_spectrum, "combined")
    payload: SpectrumSeriesPayload = {
        "x": float_list(x_axis["amp"]),
        "y": float_list(y_axis["amp"]),
        "z": float_list(z_axis["amp"]),
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


def build_selected_payload(
    buf: ClientBuffer,
    client_id: str,
    *,
    sample_rate_hz: int,
    waveform_seconds: int,
    waveform_display_hz: int,
    latest_fn: Callable[[ClientBuffer, int], np.ndarray],
) -> SelectedClientPayload:
    """Build the selected-client detailed payload (waveform + spectrum + metrics).

    Parameters
    ----------
    buf:
        The client's circular buffer (already under lock).
    client_id:
        ID of the selected client.
    sample_rate_hz:
        Effective sample rate.
    waveform_seconds:
        Time window for the waveform display.
    waveform_display_hz:
        Target display refresh rate for waveform decimation.
    latest_fn:
        Callable ``(buf, n) -> ndarray`` to extract the latest *n* samples.
    """
    sr = buf.sample_rate_hz or sample_rate_hz
    no_data = buf.count == 0
    if no_data or sr <= 0:
        return {
            "client_id": client_id,
            "sample_rate_hz": sr,
            "waveform": {},
            "spectrum": {},
            "metrics": {},
        }
    selected_cache_key = (buf.ingest_generation, buf.spectrum_generation, sr)
    if (
        buf.cached_selected_payload is not None
        and buf.cached_selected_payload_key == selected_cache_key
    ):
        return buf.cached_selected_payload
    window_samples = min(
        buf.count,
        buf.capacity,
        max(1, int(sr * max(1, waveform_seconds))),
    )
    waveform_raw = latest_fn(buf, window_samples)
    waveform_step = max(1, sr // max(1, waveform_display_hz))
    decimated = waveform_raw[:, ::waveform_step]
    points = decimated.shape[1]
    x = (np.arange(points, dtype=np.float32) - (points - 1)) * (waveform_step / sr)

    waveform: WaveformPayload = {"t": float_list(x)}
    for axis_idx, axis in enumerate(AXES):
        waveform[axis] = float_list(decimated[axis_idx])

    spectrum: SelectedSpectrumPayload
    if buf.latest_spectrum:
        x_axis: SpectrumAxisData = _axis_data_or_empty(buf.latest_spectrum, "x")
        freq = x_axis["freq"]
        spectrum = {
            "freq": float_list(freq),
            "x": [],
            "y": [],
            "z": [],
            "combined_spectrum_amp_g": [],
            "strength_metrics": buf.latest_strength_metrics,
        }
        for axis in AXES:
            axis_data: SpectrumAxisData = _axis_data_or_empty(buf.latest_spectrum, axis)
            spectrum[axis] = float_list(axis_data["amp"])
        combined = _axis_data_or_empty(buf.latest_spectrum, "combined")
        spectrum["combined_spectrum_amp_g"] = float_list(combined["amp"])
    else:
        spectrum = {
            "freq": [],
            "x": [],
            "y": [],
            "z": [],
            "combined_spectrum_amp_g": [],
            "strength_metrics": {},
        }

    payload: SelectedClientPayload = {
        "client_id": client_id,
        "sample_rate_hz": sr,
        "waveform": waveform,
        "spectrum": spectrum,
        "metrics": buf.latest_metrics,
    }
    buf.cached_selected_payload = payload
    buf.cached_selected_payload_key = selected_cache_key
    return payload
