from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

AXES = ("x", "y", "z")
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ClientBuffer:
    data: np.ndarray
    write_idx: int = 0
    count: int = 0
    sample_rate_hz: int = 0
    latest_metrics: dict[str, Any] = field(default_factory=dict)
    latest_spectrum: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)


class SignalProcessor:
    def __init__(
        self,
        sample_rate_hz: int,
        waveform_seconds: int,
        waveform_display_hz: int,
        fft_n: int,
        spectrum_max_hz: int,
    ):
        self.sample_rate_hz = sample_rate_hz
        self.waveform_seconds = waveform_seconds
        self.waveform_display_hz = waveform_display_hz
        self.fft_n = fft_n
        self.spectrum_max_hz = spectrum_max_hz
        self.max_samples = sample_rate_hz * waveform_seconds
        self.waveform_step = max(1, sample_rate_hz // max(1, waveform_display_hz))
        self._buffers: dict[str, ClientBuffer] = {}
        self._fft_window = np.hanning(self.fft_n).astype(np.float32)
        self._fft_scale = float(2.0 / max(1.0, float(np.sum(self._fft_window))))
        self._fft_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def _get_or_create(self, client_id: str) -> ClientBuffer:
        buf = self._buffers.get(client_id)
        if buf is None:
            data = np.zeros((3, self.max_samples), dtype=np.float32)
            buf = ClientBuffer(data=data)
            self._buffers[client_id] = buf
        return buf

    def ingest(
        self,
        client_id: str,
        samples: np.ndarray,
        sample_rate_hz: int | None = None,
    ) -> None:
        if samples.size == 0:
            return
        buf = self._get_or_create(client_id)
        chunk = np.asarray(samples, dtype=np.float32)
        if chunk.ndim != 2 or chunk.shape[1] != 3:
            LOGGER.warning(
                "Dropping malformed sample chunk for %s with shape %s",
                client_id,
                chunk.shape,
            )
            return
        if sample_rate_hz is not None and sample_rate_hz > 0:
            buf.sample_rate_hz = int(sample_rate_hz)

        n = int(chunk.shape[0])
        if n >= self.max_samples:
            chunk = chunk[-self.max_samples :]
            n = self.max_samples

        end = buf.write_idx + n
        if end <= self.max_samples:
            buf.data[:, buf.write_idx : end] = chunk.T
        else:
            first = self.max_samples - buf.write_idx
            buf.data[:, buf.write_idx :] = chunk[:first].T
            buf.data[:, : end % self.max_samples] = chunk[first:].T

        buf.write_idx = end % self.max_samples
        buf.count = min(self.max_samples, buf.count + n)

    def _latest(self, buf: ClientBuffer, n: int) -> np.ndarray:
        if n <= 0 or buf.count == 0:
            return np.empty((3, 0), dtype=np.float32)
        n = min(n, buf.count)
        start = (buf.write_idx - n) % self.max_samples
        if start + n <= self.max_samples:
            return buf.data[:, start : start + n]
        first = self.max_samples - start
        return np.concatenate((buf.data[:, start:], buf.data[:, : n - first]), axis=1)

    @staticmethod
    def _top_peaks(freqs: np.ndarray, amps: np.ndarray, top_n: int = 3) -> list[dict[str, float]]:
        if len(freqs) == 0:
            return []
        if len(freqs) <= top_n:
            order = np.argsort(amps)[::-1]
        else:
            idx = np.argpartition(amps, -top_n)[-top_n:]
            order = idx[np.argsort(amps[idx])[::-1]]
        return [{"hz": float(freqs[i]), "amp": float(amps[i])} for i in order]

    def _fft_params(self, sample_rate_hz: int) -> tuple[np.ndarray, np.ndarray]:
        cached = self._fft_cache.get(sample_rate_hz)
        if cached is not None:
            return cached
        freqs = np.fft.rfftfreq(self.fft_n, d=1.0 / sample_rate_hz)
        valid = freqs <= self.spectrum_max_hz
        freq_slice = freqs[valid].astype(np.float32)
        valid_idx = np.flatnonzero(valid)
        self._fft_cache[sample_rate_hz] = (freq_slice, valid_idx)
        return freq_slice, valid_idx

    def compute_metrics(self, client_id: str, sample_rate_hz: int | None = None) -> dict[str, Any]:
        buf = self._buffers.get(client_id)
        if buf is None or buf.count == 0:
            return {}
        if sample_rate_hz is not None and sample_rate_hz > 0:
            buf.sample_rate_hz = int(sample_rate_hz)
        sr = buf.sample_rate_hz or self.sample_rate_hz

        n_time = min(buf.count, self.max_samples)
        time_window = self._latest(buf, n_time)

        metrics: dict[str, Any] = {}
        for axis_idx, axis in enumerate(AXES):
            axis_data = time_window[axis_idx]
            if axis_data.size == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(axis_data), dtype=np.float64)))
            p2p = float(np.max(axis_data) - np.min(axis_data))
            metrics[axis] = {
                "rms": rms,
                "p2p": p2p,
                "peaks": [],
            }

        if buf.count >= self.fft_n:
            fft_block = self._latest(buf, self.fft_n)
            freq_slice, valid_idx = self._fft_params(sr)
            spectrum_by_axis: dict[str, dict[str, np.ndarray]] = {}

            for axis_idx, axis in enumerate(AXES):
                spec = np.abs(
                    np.fft.rfft(fft_block[axis_idx] * self._fft_window),
                ).astype(np.float32)
                spec *= self._fft_scale
                if spec.size > 0:
                    spec[0] *= 0.5
                if (self.fft_n % 2) == 0 and spec.size > 1:
                    spec[-1] *= 0.5
                amp_slice = spec[valid_idx]
                if amp_slice.size > 1:
                    amp_for_peaks = amp_slice.copy()
                    amp_for_peaks[0] = 0.0
                else:
                    amp_for_peaks = amp_slice
                metrics.setdefault(axis, {"rms": 0.0, "p2p": 0.0, "peaks": []})
                metrics[axis]["peaks"] = self._top_peaks(freq_slice, amp_for_peaks, top_n=3)
                spectrum_by_axis[axis] = {
                    "freq": freq_slice.astype(np.float32),
                    "amp": amp_slice.astype(np.float32),
                }
            buf.latest_spectrum = spectrum_by_axis

        buf.latest_metrics = metrics
        return metrics

    def compute_all(
        self,
        client_ids: list[str],
        sample_rates_hz: dict[str, int] | None = None,
    ) -> dict[str, dict[str, Any]]:
        rates = sample_rates_hz or {}
        return {
            client_id: self.compute_metrics(client_id, sample_rate_hz=rates.get(client_id))
            for client_id in client_ids
        }

    def spectrum_payload(self, client_id: str) -> dict[str, Any]:
        buf = self._buffers.get(client_id)
        if buf is None or not buf.latest_spectrum:
            return {"x": [], "y": [], "z": []}
        return {
            "x": buf.latest_spectrum["x"]["amp"].tolist(),
            "y": buf.latest_spectrum["y"]["amp"].tolist(),
            "z": buf.latest_spectrum["z"]["amp"].tolist(),
        }

    def multi_spectrum_payload(self, client_ids: list[str]) -> dict[str, Any]:
        freq: list[float] = []
        clients: dict[str, dict[str, list[float]]] = {}
        for client_id in client_ids:
            buf = self._buffers.get(client_id)
            if buf is None or not buf.latest_spectrum:
                continue
            if not freq:
                freq = buf.latest_spectrum["x"]["freq"].tolist()
            clients[client_id] = self.spectrum_payload(client_id)
        return {"freq": freq, "clients": clients}

    def selected_payload(self, client_id: str) -> dict[str, Any]:
        buf = self._buffers.get(client_id)
        if buf is None or buf.count == 0:
            return {
                "client_id": client_id,
                "sample_rate_hz": self.sample_rate_hz,
                "waveform": {},
                "spectrum": {},
                "metrics": {},
            }

        waveform_raw = self._latest(buf, buf.count)
        sr = buf.sample_rate_hz or self.sample_rate_hz
        waveform_step = max(1, sr // max(1, self.waveform_display_hz))
        decimated = waveform_raw[:, :: waveform_step]
        points = decimated.shape[1]
        x = (
            (np.arange(points, dtype=np.float32) - (points - 1))
            * (waveform_step / sr)
        )

        waveform = {"t": x.tolist()}
        for axis_idx, axis in enumerate(AXES):
            waveform[axis] = decimated[axis_idx].astype(np.float32).tolist()

        spectrum: dict[str, Any] = {}
        if buf.latest_spectrum:
            freq = buf.latest_spectrum["x"]["freq"]
            spectrum["freq"] = freq.tolist()
            for axis in AXES:
                spectrum[axis] = buf.latest_spectrum[axis]["amp"].tolist()
        else:
            spectrum = {"freq": [], "x": [], "y": [], "z": []}

        return {
            "client_id": client_id,
            "sample_rate_hz": sr,
            "waveform": waveform,
            "spectrum": spectrum,
            "metrics": buf.latest_metrics,
        }

    def evict_clients(self, keep_client_ids: set[str]) -> None:
        stale_ids = [
            client_id
            for client_id in self._buffers.keys()
            if client_id not in keep_client_ids
        ]
        for client_id in stale_ids:
            self._buffers.pop(client_id, None)
