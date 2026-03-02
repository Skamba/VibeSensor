"""Signal processor — buffer management, metric computation, and payload formatting.

``SignalProcessor`` is the stateful coordinator that manages per-client
circular buffers, dispatches FFT computation to the pure functions in
:mod:`~vibesensor.processing.fft`, and assembles API/WebSocket payloads.

Thread-safety is maintained through an internal :class:`threading.RLock`;
the ``@_synchronized`` decorator is applied to methods that read or
mutate shared buffer state.
"""

from __future__ import annotations

import logging
import math
import time
from functools import wraps
from threading import RLock
from typing import Any

import numpy as np

from ..worker_pool import WorkerPool
from .buffers import ClientBuffer
from .fft import (
    AXES,
    compute_fft_spectrum,
    float_list,
    medfilt3,
    top_peaks,
)
from .time_align import (
    analysis_time_range,
    compute_overlap,
)

LOGGER = logging.getLogger(__name__)
MAX_CLIENT_SAMPLE_RATE_HZ = 4096
_FFT_CACHE_MAXSIZE = 64
"""Maximum number of cached FFT plans.  Bounds memory while avoiding
repeated plan recomputation for common (sample_rate, fft_size) pairs."""


def _synchronized(method):
    @wraps(method)
    def _wrapped(self: SignalProcessor, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return _wrapped


class SignalProcessor:
    def __init__(
        self,
        sample_rate_hz: int,
        waveform_seconds: int,
        waveform_display_hz: int,
        fft_n: int,
        spectrum_min_hz: float = 0.0,
        spectrum_max_hz: int = 200,
        accel_scale_g_per_lsb: float | None = None,
        worker_pool: WorkerPool | None = None,
    ):
        self.sample_rate_hz = sample_rate_hz
        self.waveform_seconds = waveform_seconds
        self.waveform_display_hz = waveform_display_hz
        self.fft_n = fft_n
        self.spectrum_min_hz = max(0.0, float(spectrum_min_hz))
        self.spectrum_max_hz = spectrum_max_hz
        self.accel_scale_g_per_lsb = (
            float(accel_scale_g_per_lsb)
            if isinstance(accel_scale_g_per_lsb, (int, float)) and accel_scale_g_per_lsb > 0
            else None
        )
        self.max_samples = sample_rate_hz * waveform_seconds
        self.waveform_step = max(1, sample_rate_hz // max(1, waveform_display_hz))
        self._buffers: dict[str, ClientBuffer] = {}
        self._fft_window = np.hanning(self.fft_n).astype(np.float32)
        self._fft_scale = float(2.0 / max(1.0, float(np.sum(self._fft_window))))
        self._fft_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._fft_cache_maxsize = _FFT_CACHE_MAXSIZE
        self._fft_cache_lock = RLock()
        self._spike_filter_enabled = True
        self._lock = RLock()
        # Worker pool for parallel per-client FFT.  Owned externally when
        # injected, otherwise a private pool is created.
        self._worker_pool = worker_pool
        # Lightweight intake/analysis metrics for observability.
        self._total_ingested_samples: int = 0
        self._total_compute_calls: int = 0
        self._last_compute_duration_s: float = 0.0
        self._last_compute_all_duration_s: float = 0.0
        self._last_ingest_duration_s: float = 0.0

    # -- static / pure helpers (delegate to fft module) -----------------------

    @staticmethod
    def _medfilt3(block: np.ndarray) -> np.ndarray:
        return medfilt3(block)

    @staticmethod
    def _smooth_spectrum(amps: np.ndarray, bins: int = 5) -> np.ndarray:
        from .fft import smooth_spectrum

        return smooth_spectrum(amps, bins=bins)

    @staticmethod
    def _noise_floor(amps: np.ndarray) -> float:
        from .fft import noise_floor

        return noise_floor(amps)

    @staticmethod
    def _float_list(values: np.ndarray | list[float]) -> list[float]:
        return float_list(values)

    @classmethod
    def _top_peaks(
        cls,
        freqs: np.ndarray,
        amps: np.ndarray,
        *,
        top_n: int = 5,
        floor_ratio: float = ...,  # type: ignore[assignment]
        smoothing_bins: int = 5,
    ) -> list[dict[str, float]]:
        kwargs: dict[str, Any] = {"top_n": top_n, "smoothing_bins": smoothing_bins}
        if floor_ratio is not ...:
            kwargs["floor_ratio"] = floor_ratio
        return top_peaks(freqs, amps, **kwargs)

    # -- Buffer management ----------------------------------------------------

    @_synchronized
    def flush_client_buffer(self, client_id: str) -> None:
        """Reset the buffer for *client_id*, discarding all stored samples.

        After a sensor reset (sequence-number wraparound, new HELLO with
        different firmware, etc.) the circular buffer likely contains samples
        from a different time-base.  Flushing ensures the next FFT window
        is built entirely from post-reset data.
        """
        buf = self._buffers.get(client_id)
        if buf is None:
            return
        buf.data[:] = 0.0
        buf.write_idx = 0
        buf.count = 0
        buf.first_ingest_mono_s = 0.0
        buf.last_t0_us = 0
        buf.samples_since_t0 = 0
        buf.latest_metrics = {}
        buf.latest_spectrum = {}
        buf.latest_strength_metrics = {}
        buf.invalidate_caches()
        buf.ingest_generation += 1
        LOGGER.info("Flushed signal buffer for client %s after sensor reset", client_id)

    def _get_or_create(self, client_id: str) -> ClientBuffer:
        buf = self._buffers.get(client_id)
        if buf is None:
            data = np.zeros((3, self.max_samples), dtype=np.float32)
            buf = ClientBuffer(data=data, capacity=self.max_samples)
            self._buffers[client_id] = buf
        return buf

    def _resize_buffer(self, buf: ClientBuffer, new_capacity: int) -> None:
        new_capacity = max(1, int(new_capacity))
        if new_capacity == buf.capacity:
            return
        latest = self._latest(buf, min(buf.count, new_capacity))
        resized = np.zeros((3, new_capacity), dtype=np.float32)
        if latest.size:
            resized[:, : latest.shape[1]] = latest
        buf.data = resized
        buf.capacity = new_capacity
        buf.write_idx = latest.shape[1] % new_capacity
        buf.count = min(latest.shape[1], new_capacity)

    @_synchronized
    def ingest(
        self,
        client_id: str,
        samples: np.ndarray,
        sample_rate_hz: int | None = None,
        t0_us: int | None = None,
    ) -> None:
        t_start = time.monotonic()
        if samples.size == 0:
            return
        buf = self._get_or_create(client_id)
        chunk = np.asarray(samples, dtype=np.float32)
        if self.accel_scale_g_per_lsb is not None:
            chunk = chunk * np.float32(self.accel_scale_g_per_lsb)
        if chunk.ndim != 2 or chunk.shape[1] != 3:
            LOGGER.warning(
                "Dropping malformed sample chunk for %s with shape %s",
                client_id,
                chunk.shape,
            )
            return
        if sample_rate_hz is not None and sample_rate_hz > 0:
            requested_rate = int(sample_rate_hz)
            clamped_rate = max(1, min(MAX_CLIENT_SAMPLE_RATE_HZ, requested_rate))
            if clamped_rate != requested_rate:
                LOGGER.warning(
                    "Clamped client sample_rate_hz from %d to %d to bound buffer growth",
                    requested_rate,
                    clamped_rate,
                )
            buf.sample_rate_hz = clamped_rate
            self._resize_buffer(buf, buf.sample_rate_hz * self.waveform_seconds)
        now_mono = time.monotonic()
        if buf.first_ingest_mono_s <= 0:
            buf.first_ingest_mono_s = now_mono
        buf.last_ingest_mono_s = now_mono

        n = int(chunk.shape[0])
        capacity = buf.capacity
        if n >= capacity:
            chunk = chunk[-capacity:]
            n = capacity

        end = buf.write_idx + n
        if end <= capacity:
            buf.data[:, buf.write_idx : end] = chunk.T
        else:
            first = capacity - buf.write_idx
            buf.data[:, buf.write_idx :] = chunk[:first].T
            buf.data[:, : end % capacity] = chunk[first:].T

        buf.write_idx = end % capacity
        buf.count = min(capacity, buf.count + n)
        # Track sensor-clock timestamp for cross-sensor alignment.
        if t0_us is not None and t0_us > 0:
            buf.last_t0_us = int(t0_us)
            buf.samples_since_t0 = n
        else:
            buf.samples_since_t0 += n
        buf.ingest_generation += 1
        buf.invalidate_caches()
        self._total_ingested_samples += n
        self._last_ingest_duration_s = time.monotonic() - t_start

    def _latest(self, buf: ClientBuffer, n: int) -> np.ndarray:
        if n <= 0 or buf.count == 0:
            return np.empty((3, 0), dtype=np.float32)
        n = min(n, buf.count)
        start = (buf.write_idx - n) % buf.capacity
        if start + n <= buf.capacity:
            return buf.data[:, start : start + n].copy()
        first = buf.capacity - start
        return np.concatenate((buf.data[:, start:], buf.data[:, : n - first]), axis=1)

    # -- FFT / metric computation ---------------------------------------------

    def _fft_params(self, sample_rate_hz: int) -> tuple[np.ndarray, np.ndarray]:
        with self._fft_cache_lock:
            cached = self._fft_cache.get(sample_rate_hz)
            if cached is not None:
                return cached
            if sample_rate_hz <= 0:
                empty = np.empty(0, dtype=np.float32)
                return empty, np.empty(0, dtype=np.intp)
            freqs = np.fft.rfftfreq(self.fft_n, d=1.0 / sample_rate_hz)
            valid = (freqs >= self.spectrum_min_hz) & (freqs <= self.spectrum_max_hz)
            freq_slice = freqs[valid].astype(np.float32)
            valid_idx = np.flatnonzero(valid)
            self._fft_cache[sample_rate_hz] = (freq_slice, valid_idx)
            if len(self._fft_cache) > self._fft_cache_maxsize:
                oldest = next(iter(self._fft_cache))
                del self._fft_cache[oldest]
            return freq_slice, valid_idx

    def _compute_fft_spectrum(
        self,
        fft_block: np.ndarray,
        sample_rate_hz: int,
    ) -> dict[str, Any]:
        """Shared FFT spectrum computation used by both compute_metrics and debug_spectrum.

        Delegates to the pure :func:`~vibesensor.processing.fft.compute_fft_spectrum`
        function, passing processor configuration as parameters.
        """
        freq_slice, valid_idx = self._fft_params(sample_rate_hz)
        return compute_fft_spectrum(
            fft_block,
            sample_rate_hz,
            fft_window=self._fft_window,
            fft_scale=self._fft_scale,
            freq_slice=freq_slice,
            valid_idx=valid_idx,
            spike_filter_enabled=self._spike_filter_enabled,
        )

    def compute_metrics(self, client_id: str, sample_rate_hz: int | None = None) -> dict[str, Any]:
        t0 = time.monotonic()
        # --- Phase 1: snapshot buffer state under a brief lock ---------------
        with self._lock:
            buf = self._buffers.get(client_id)
            if buf is None or buf.count == 0:
                return {}
            if sample_rate_hz is not None and sample_rate_hz > 0:
                buf.sample_rate_hz = int(sample_rate_hz)
            sr = buf.sample_rate_hz or self.sample_rate_hz
            # Fast-path: no new ingested samples at this sample-rate, so keep
            # the previously computed metrics/spectrum snapshot for payload reuse.
            if buf.compute_generation == buf.ingest_generation and buf.compute_sample_rate_hz == sr:
                return buf.latest_metrics

            desired_samples = int(max(1.0, float(sr) * float(self.waveform_seconds)))
            n_time = min(buf.count, buf.capacity, max(1, desired_samples))
            time_window = self._latest(buf, n_time)  # returns a copy
            has_fft_data = buf.count >= self.fft_n
            fft_block = self._latest(buf, self.fft_n) if has_fft_data else None
            snap_ingest_gen = buf.ingest_generation

        # --- Phase 2: heavy computation (no lock held) -----------------------
        if self._spike_filter_enabled:
            time_window = medfilt3(time_window)
        time_window_detrended = time_window - np.mean(time_window, axis=1, keepdims=True)

        metrics: dict[str, Any] = {}
        for axis_idx, axis in enumerate(AXES):
            axis_data = time_window_detrended[axis_idx]
            if axis_data.size == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(axis_data), dtype=np.float64)))
            p2p = float(np.max(axis_data) - np.min(axis_data))
            if not math.isfinite(rms):
                rms = 0.0
            if not math.isfinite(p2p):
                p2p = 0.0
            metrics[axis] = {
                "rms": rms,
                "p2p": p2p,
                "peaks": [],
            }

        if time_window_detrended.size > 0:
            vib_mag = np.sqrt(np.sum(np.square(time_window_detrended, dtype=np.float64), axis=0))
            vib_mag_rms = float(np.sqrt(np.mean(np.square(vib_mag), dtype=np.float64)))
            vib_mag_p2p = float(np.max(vib_mag) - np.min(vib_mag))
            if not math.isfinite(vib_mag_rms):
                vib_mag_rms = 0.0
            if not math.isfinite(vib_mag_p2p):
                vib_mag_p2p = 0.0
        else:
            vib_mag_rms = 0.0
            vib_mag_p2p = 0.0

        metrics["combined"] = {
            "vib_mag_rms": vib_mag_rms,
            "vib_mag_p2p": vib_mag_p2p,
            "peaks": [],
        }

        spectrum_by_axis: dict[str, dict[str, np.ndarray]] = {}
        strength_metrics_dict: dict[str, Any] = {}
        if has_fft_data and fft_block is not None:
            fft_result = self._compute_fft_spectrum(fft_block, sr)
            freq_slice = fft_result["freq_slice"]
            spectrum_by_axis = fft_result["spectrum_by_axis"]

            for axis in fft_result["axis_peaks"]:
                metrics.setdefault(axis, {"rms": 0.0, "p2p": 0.0, "peaks": []})
                metrics[axis]["peaks"] = fft_result["axis_peaks"][axis]

            if fft_result["axis_amp_slices"]:
                combined_amp = fft_result["combined_amp"]
                strength_metrics = fft_result["strength_metrics"]
                metrics["combined"]["peaks"] = list(strength_metrics["top_peaks"])
                metrics["combined"]["strength_metrics"] = dict(strength_metrics)
                metrics["strength_metrics"] = dict(strength_metrics)
                spectrum_by_axis["combined"] = {
                    "freq": freq_slice,
                    "amp": combined_amp,
                }
                strength_metrics_dict = dict(strength_metrics)

        # --- Phase 3: store results under a brief lock -----------------------
        with self._lock:
            buf = self._buffers.get(client_id)
            if buf is not None and snap_ingest_gen >= buf.compute_generation:
                buf.latest_metrics = metrics
                buf.compute_generation = snap_ingest_gen
                buf.compute_sample_rate_hz = sr
                if has_fft_data:
                    buf.latest_spectrum = spectrum_by_axis
                    buf.latest_strength_metrics = strength_metrics_dict
                else:
                    buf.latest_spectrum = {}
                    buf.latest_strength_metrics = {}
                buf.spectrum_generation += 1
                buf.invalidate_caches()
        self._last_compute_duration_s = time.monotonic() - t0
        self._total_compute_calls += 1
        return metrics

    def compute_all(
        self,
        client_ids: list[str],
        sample_rates_hz: dict[str, int] | None = None,
    ) -> dict[str, dict[str, Any]]:
        rates = sample_rates_hz or {}
        if len(client_ids) <= 1 or self._worker_pool is None:
            # Fast path: single client or no pool – avoid thread overhead.
            t0 = time.monotonic()
            result: dict[str, dict[str, Any]] = {}
            for client_id in client_ids:
                try:
                    result[client_id] = self.compute_metrics(
                        client_id,
                        sample_rate_hz=rates.get(client_id),
                    )
                except Exception:
                    LOGGER.warning(
                        "compute_metrics failed for %s; skipping.",
                        client_id,
                        exc_info=True,
                    )
            self._last_compute_all_duration_s = time.monotonic() - t0
            return result

        # Parallel path: submit per-client FFT work to the pool.
        t0 = time.monotonic()

        def _compute_one(client_id: str) -> dict[str, Any]:
            return self.compute_metrics(client_id, sample_rate_hz=rates.get(client_id))

        result = self._worker_pool.map_unordered(_compute_one, client_ids)
        self._last_compute_all_duration_s = time.monotonic() - t0
        return result

    # -- Payload formatting ---------------------------------------------------

    @_synchronized
    def spectrum_payload(self, client_id: str) -> dict[str, Any]:
        buf = self._buffers.get(client_id)
        if buf is None or not buf.latest_spectrum:
            return {
                "x": [],
                "y": [],
                "z": [],
                "combined_spectrum_amp_g": [],
                "strength_metrics": {},
            }
        if (
            buf.cached_spectrum_payload is not None
            and buf.cached_spectrum_payload_generation == buf.spectrum_generation
        ):
            return buf.cached_spectrum_payload
        _empty = np.array([], dtype=np.float32)
        payload = {
            "x": float_list(buf.latest_spectrum.get("x", {}).get("amp", _empty)),
            "y": float_list(buf.latest_spectrum.get("y", {}).get("amp", _empty)),
            "z": float_list(buf.latest_spectrum.get("z", {}).get("amp", _empty)),
            "combined_spectrum_amp_g": (
                float_list(buf.latest_spectrum.get("combined", {}).get("amp", _empty))
            ),
            "strength_metrics": dict(buf.latest_strength_metrics),
        }
        buf.cached_spectrum_payload = payload
        buf.cached_spectrum_payload_generation = buf.spectrum_generation
        return payload

    @_synchronized
    def multi_spectrum_payload(self, client_ids: list[str]) -> dict[str, Any]:
        shared_freq: np.ndarray | None = None
        clients: dict[str, dict[str, Any]] = {}
        mismatch_ids: list[str] = []
        # Track per-client freq arrays so we can decide later whether to
        # include them per-client or only at the top level.
        per_client_freq: dict[str, np.ndarray] = {}

        # --- Compute per-sensor time ranges for alignment metadata -----------
        ranges: list[tuple[str, float, float]] = []
        any_synced = False
        all_synced = True
        for client_id in client_ids:
            buf = self._buffers.get(client_id)
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
            clients[client_id] = self.spectrum_payload(client_id)

            tr = self._analysis_time_range(buf)
            if tr is not None:
                ranges.append((client_id, tr[0], tr[1]))
                if tr[2]:
                    any_synced = True
                else:
                    all_synced = False

        # When all clients share the same frequency axis, emit a single
        # top-level "freq" and omit per-client "freq" to reduce payload size.
        if mismatch_ids:
            # Axes differ: include per-client freq and clear shared.
            for cid, freq_arr in per_client_freq.items():
                clients[cid]["freq"] = float_list(freq_arr)
            shared_freq_list: list[float] = []
        else:
            # All axes match: shared freq only, no per-client duplication.
            shared_freq_list = float_list(shared_freq) if shared_freq is not None else []

        payload: dict[str, Any] = {
            "freq": shared_freq_list,
            "clients": clients,
        }
        if mismatch_ids:
            payload["warning"] = {
                "code": "frequency_bin_mismatch",
                "message": "Per-client frequency axes returned due to sample-rate mismatch.",
                "client_ids": sorted(mismatch_ids),
            }

        # --- Alignment metadata ----------------------------------------------
        if len(ranges) >= 2:
            ov = compute_overlap(
                [s for _, s, _ in ranges],
                [e for _, _, e in ranges],
            )
            payload["alignment"] = {
                "overlap_ratio": round(ov.overlap_ratio, 4),
                "aligned": ov.aligned,
                "shared_window_s": round(ov.overlap_s, 4),
                "sensor_count": len(ranges),
                "clock_synced": all_synced and any_synced,
            }
        return payload

    @_synchronized
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

        sr = buf.sample_rate_hz or self.sample_rate_hz
        if sr <= 0:
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
            max(1, int(sr * max(1, self.waveform_seconds))),
        )
        waveform_raw = self._latest(buf, window_samples)
        waveform_step = max(1, sr // max(1, self.waveform_display_hz))
        decimated = waveform_raw[:, ::waveform_step]
        points = decimated.shape[1]
        x = (np.arange(points, dtype=np.float32) - (points - 1)) * (waveform_step / sr)

        waveform = {"t": float_list(x)}
        for axis_idx, axis in enumerate(AXES):
            waveform[axis] = float_list(decimated[axis_idx])

        spectrum: dict[str, Any] = {}
        if buf.latest_spectrum:
            x_axis = buf.latest_spectrum.get("x", {})
            freq = x_axis.get("freq", np.array([], dtype=np.float32))
            spectrum["freq"] = float_list(freq)
            for axis in AXES:
                axis_data = buf.latest_spectrum.get(axis, {})
                _empty = np.array([], dtype=np.float32)
                spectrum[axis] = float_list(axis_data.get("amp", _empty))
            combined = buf.latest_spectrum.get("combined")
            spectrum["combined_spectrum_amp_g"] = (
                float_list(combined["amp"])
                if isinstance(combined, dict) and "amp" in combined
                else []
            )
            spectrum["strength_metrics"] = dict(buf.latest_strength_metrics)
        else:
            spectrum = {
                "freq": [],
                "x": [],
                "y": [],
                "z": [],
                "combined_spectrum_amp_g": [],
                "strength_metrics": {},
            }

        payload = {
            "client_id": client_id,
            "sample_rate_hz": sr,
            "waveform": waveform,
            "spectrum": spectrum,
            "metrics": buf.latest_metrics,
        }
        buf.cached_selected_payload = payload
        buf.cached_selected_payload_key = selected_cache_key
        return payload

    # -- Accessors & debug ----------------------------------------------------

    @_synchronized
    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None:
        buf = self._buffers.get(client_id)
        if buf is None or buf.count == 0:
            return None
        idx = (buf.write_idx - 1) % buf.capacity
        return (
            float(buf.data[0, idx]),
            float(buf.data[1, idx]),
            float(buf.data[2, idx]),
        )

    @_synchronized
    def latest_sample_rate_hz(self, client_id: str) -> int | None:
        buf = self._buffers.get(client_id)
        if buf is None:
            return None
        rate = int(buf.sample_rate_hz or 0)
        return rate if rate > 0 else None

    @_synchronized
    def debug_spectrum(self, client_id: str) -> dict[str, Any]:
        """Return detailed spectrum debug info for independent verification."""
        buf = self._buffers.get(client_id)
        if buf is None or buf.count < self.fft_n:
            return {
                "error": "insufficient samples",
                "count": buf.count if buf else 0,
                "fft_n": self.fft_n,
            }
        sr = buf.sample_rate_hz or self.sample_rate_hz
        fft_block = self._latest(buf, self.fft_n).copy()

        # Stats before filtering / mean removal
        raw_mean = [float(fft_block[i].mean()) for i in range(3)]
        raw_std = [float(fft_block[i].std()) for i in range(3)]
        raw_min = [float(fft_block[i].min()) for i in range(3)]
        raw_max = [float(fft_block[i].max()) for i in range(3)]

        # Use shared FFT computation (same path as compute_metrics)
        fft_result = self._compute_fft_spectrum(fft_block, sr)
        freq_slice = fft_result["freq_slice"]
        axis_amps = fft_result["axis_amps"]
        combined_amp = fft_result["combined_amp"]
        sm = fft_result["strength_metrics"]

        # Detrended std from the filtered block (approximate from axis amps)
        detrended_std = [float(np.std(fft_block[i] - np.mean(fft_block[i]))) for i in range(3)]

        # Top 10 bins by combined amplitude
        sorted_idx = np.argsort(combined_amp)[::-1]
        top_bins = []
        for i in sorted_idx[:10]:
            top_bins.append(
                {
                    "bin": int(i),
                    "freq_hz": float(freq_slice[i]),
                    "combined_amp_g": float(combined_amp[i]),
                    "x_amp_g": float(axis_amps["x"][i]),
                    "y_amp_g": float(axis_amps["y"][i]),
                    "z_amp_g": float(axis_amps["z"][i]),
                }
            )

        return {
            "client_id": client_id,
            "sample_rate_hz": sr,
            "fft_n": self.fft_n,
            "fft_scale": self._fft_scale,
            "window": "hann",
            "spectrum_min_hz": self.spectrum_min_hz,
            "spectrum_max_hz": self.spectrum_max_hz,
            "freq_bins": len(freq_slice),
            "freq_resolution_hz": float(sr) / self.fft_n,
            "raw_stats": {
                "mean_g": raw_mean,
                "std_g": raw_std,
                "min_g": raw_min,
                "max_g": raw_max,
            },
            "detrended_std_g": detrended_std,
            "vibration_strength_db": float(sm.get("vibration_strength_db", 0)),
            "top_bins_by_amplitude": top_bins,
            "strength_peaks": list(sm.get("top_peaks", [])),
        }

    @_synchronized
    def raw_samples(self, client_id: str, n_samples: int = 2048) -> dict[str, Any]:
        """Return raw time-domain samples (in g) for independent analysis."""
        buf = self._buffers.get(client_id)
        if buf is None or buf.count == 0:
            return {"error": "no data", "count": 0}
        sr = buf.sample_rate_hz or self.sample_rate_hz
        n = min(n_samples, buf.count)
        block = self._latest(buf, n)
        return {
            "client_id": client_id,
            "sample_rate_hz": sr,
            "n_samples": n,
            "x": float_list(block[0]),
            "y": float_list(block[1]),
            "z": float_list(block[2]),
        }

    @_synchronized
    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        """Return subset of *client_ids* that received data within *max_age_s*."""
        now = time.monotonic()
        result: list[str] = []
        for cid in client_ids:
            buf = self._buffers.get(cid)
            if buf is None or buf.last_ingest_mono_s <= 0:
                continue
            if (now - buf.last_ingest_mono_s) <= max_age_s:
                result.append(cid)
        return result

    @_synchronized
    def evict_clients(self, keep_client_ids: set[str]) -> None:
        stale_ids = [client_id for client_id in self._buffers if client_id not in keep_client_ids]
        for client_id in stale_ids:
            self._buffers.pop(client_id, None)

    def intake_stats(self) -> dict[str, Any]:
        """Return lightweight intake/analysis metrics for observability."""
        stats: dict[str, Any] = {
            "total_ingested_samples": self._total_ingested_samples,
            "total_compute_calls": self._total_compute_calls,
            "last_compute_duration_s": self._last_compute_duration_s,
            "last_compute_all_duration_s": self._last_compute_all_duration_s,
            "last_ingest_duration_s": self._last_ingest_duration_s,
        }
        if self._worker_pool is not None:
            stats["worker_pool"] = self._worker_pool.stats()
        return stats

    # -- Time-alignment helpers ------------------------------------------------

    def _analysis_time_range(self, buf: ClientBuffer) -> tuple[float, float, bool] | None:
        """Return ``(start_s, end_s, synced)`` for the current analysis window.

        Delegates to the pure :func:`~vibesensor.processing.time_align.analysis_time_range`
        function.
        """
        sr = buf.sample_rate_hz or self.sample_rate_hz
        return analysis_time_range(
            count=buf.count,
            last_ingest_mono_s=buf.last_ingest_mono_s,
            sample_rate_hz=sr,
            waveform_seconds=self.waveform_seconds,
            capacity=buf.capacity,
            last_t0_us=buf.last_t0_us,
            samples_since_t0=buf.samples_since_t0,
        )

    @_synchronized
    def time_alignment_info(self, client_ids: list[str]) -> dict[str, Any]:
        """Compute time-alignment metadata across multiple sensors.

        Returns a dict with:

        * ``per_sensor``  – per-client time-range info (includes ``synced`` flag)
        * ``shared_window`` – intersection of all time ranges (``None`` if disjoint)
        * ``overlap_ratio`` – fraction of the union covered by the intersection
        * ``aligned`` – ``True`` when the overlap ratio meets the minimum threshold
        * ``clock_synced`` – ``True`` when *all* included sensors use synced timestamps
        * ``sensors_included`` / ``sensors_excluded`` – partition of *client_ids*
        """
        per_sensor: dict[str, dict[str, Any]] = {}
        ranges: list[tuple[float, float]] = []
        included: list[str] = []
        excluded: list[str] = []
        all_synced = True

        for cid in client_ids:
            buf = self._buffers.get(cid)
            if buf is None:
                excluded.append(cid)
                continue
            tr = self._analysis_time_range(buf)
            if tr is None:
                excluded.append(cid)
                continue
            start, end, synced = tr
            if not synced:
                all_synced = False
            per_sensor[cid] = {
                "start_s": start,
                "end_s": end,
                "duration_s": end - start,
                "synced": synced,
            }
            ranges.append((start, end))
            included.append(cid)

        if len(ranges) < 2:
            return {
                "per_sensor": per_sensor,
                "shared_window": None,
                "overlap_ratio": 1.0 if len(ranges) == 1 else 0.0,
                "aligned": True,
                "clock_synced": all_synced and len(included) > 0,
                "sensors_included": included,
                "sensors_excluded": excluded,
            }

        ov = compute_overlap(
            [s for s, _ in ranges],
            [e for _, e in ranges],
        )

        shared: dict[str, float] | None = None
        if ov.overlap_s > 0:
            shared = {
                "start_s": ov.shared_start,
                "end_s": ov.shared_end,
                "duration_s": ov.overlap_s,
            }

        return {
            "per_sensor": per_sensor,
            "shared_window": shared,
            "overlap_ratio": round(ov.overlap_ratio, 4),
            "aligned": ov.aligned,
            "clock_synced": all_synced,
            "sensors_included": included,
            "sensors_excluded": excluded,
        }
