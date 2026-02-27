from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from functools import wraps
from threading import RLock
from typing import Any

import numpy as np
from vibesensor_core.vibration_strength import (
    PEAK_THRESHOLD_FLOOR_RATIO,
    STRENGTH_EPSILON_MIN_G,
    combined_spectrum_amp_g,
    compute_vibration_strength_db,
    noise_floor_amp_p20_g,
)

from .constants import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ

AXES = ("x", "y", "z")
LOGGER = logging.getLogger(__name__)
MAX_CLIENT_SAMPLE_RATE_HZ = 4096
_ALIGNMENT_MIN_OVERLAP = 0.5  # shared window must cover ≥50 % of the union


def _synchronized(method):
    @wraps(method)
    def _wrapped(self: SignalProcessor, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return _wrapped


@dataclass(slots=True)
class ClientBuffer:
    data: np.ndarray
    capacity: int
    write_idx: int = 0
    count: int = 0
    sample_rate_hz: int = 0
    latest_metrics: dict[str, Any] = field(default_factory=dict)
    latest_spectrum: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    latest_strength_metrics: dict[str, Any] = field(default_factory=dict)
    last_ingest_mono_s: float = 0.0
    first_ingest_mono_s: float = 0.0
    # Sensor-clock timestamp (µs) of the most recent ingested frame.
    # After CMD_SYNC_CLOCK this is server-relative and comparable across sensors.
    last_t0_us: int = 0
    # Number of samples ingested since last_t0_us was recorded.  Used to
    # back-compute the timestamp of the oldest sample in the analysis window.
    samples_since_t0: int = 0
    # Generation counters: ingest_generation increments on new samples,
    # compute_generation marks which ingest generation metrics reflect, and
    # spectrum_generation marks spectrum snapshot updates for payload caching.
    ingest_generation: int = 0
    compute_generation: int = -1
    compute_sample_rate_hz: int = 0
    spectrum_generation: int = 0
    cached_spectrum_payload: dict[str, Any] | None = None
    cached_spectrum_payload_generation: int = -1
    cached_selected_payload: dict[str, Any] | None = None
    cached_selected_payload_key: tuple[int, int, int] | None = None


class SignalProcessor:
    def __init__(
        self,
        sample_rate_hz: int,
        waveform_seconds: int,
        waveform_display_hz: int,
        fft_n: int,
        spectrum_max_hz: int,
        accel_scale_g_per_lsb: float | None = None,
    ):
        self.sample_rate_hz = sample_rate_hz
        self.waveform_seconds = waveform_seconds
        self.waveform_display_hz = waveform_display_hz
        self.fft_n = fft_n
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
        self._fft_cache_maxsize = 64
        self._spike_filter_enabled = True
        self._lock = RLock()
        # Lightweight intake/analysis metrics for observability.
        self._total_ingested_samples: int = 0
        self._total_compute_calls: int = 0
        self._last_compute_duration_s: float = 0.0

    @staticmethod
    def _medfilt3(block: np.ndarray) -> np.ndarray:
        """Apply a 3-point median filter per-row (per-axis).

        Eliminates isolated single-sample spikes caused by I2C bus
        glitches while preserving genuine vibration signal content.
        Edge samples are left unchanged.
        """
        if block.shape[-1] < 3:
            return block
        stacked = np.stack([block[:, :-2], block[:, 1:-1], block[:, 2:]], axis=0)
        filtered = block.copy()
        filtered[:, 1:-1] = np.median(stacked, axis=0)
        return filtered

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
        buf.cached_spectrum_payload = None
        buf.cached_spectrum_payload_generation = -1
        buf.cached_selected_payload = None
        buf.cached_selected_payload_key = None
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
        buf.cached_selected_payload = None
        buf.cached_selected_payload_key = None
        self._total_ingested_samples += n

    def _latest(self, buf: ClientBuffer, n: int) -> np.ndarray:
        if n <= 0 or buf.count == 0:
            return np.empty((3, 0), dtype=np.float32)
        n = min(n, buf.count)
        start = (buf.write_idx - n) % buf.capacity
        if start + n <= buf.capacity:
            return buf.data[:, start : start + n].copy()
        first = buf.capacity - start
        return np.concatenate((buf.data[:, start:], buf.data[:, : n - first]), axis=1)

    @staticmethod
    def _smooth_spectrum(amps: np.ndarray, bins: int = 5) -> np.ndarray:
        if amps.size == 0:
            return amps
        width = max(1, int(bins))
        if width <= 1:
            return amps.astype(np.float32, copy=True)
        if (width % 2) == 0:
            width += 1
        if amps.size < width:
            return amps.astype(np.float32, copy=True)
        kernel = np.ones(width, dtype=np.float32) / np.float32(width)
        return np.convolve(amps, kernel, mode="same").astype(np.float32)

    @staticmethod
    def _noise_floor(amps: np.ndarray) -> float:
        """P20 noise floor delegating to the canonical core-lib implementation."""
        if amps.size == 0:
            return 0.0
        band = amps[1:] if amps.size > 1 else amps
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            return 0.0
        return noise_floor_amp_p20_g(
            combined_spectrum_amp_g=sorted(float(v) for v in finite if v >= 0.0)
        )

    @staticmethod
    def _float_list(values: np.ndarray | list[float]) -> list[float]:
        flat = values.ravel() if isinstance(values, np.ndarray) else values
        return [float(v) for v in flat]

    @classmethod
    def _top_peaks(
        cls,
        freqs: np.ndarray,
        amps: np.ndarray,
        *,
        top_n: int = 5,
        floor_ratio: float = PEAK_THRESHOLD_FLOOR_RATIO,
        smoothing_bins: int = 5,
    ) -> list[dict[str, float]]:
        if freqs.size == 0 or amps.size == 0:
            return []
        smoothed = cls._smooth_spectrum(amps, bins=smoothing_bins)
        floor_amp = cls._noise_floor(smoothed)
        threshold = max(floor_amp * max(1.1, floor_ratio), floor_amp + STRENGTH_EPSILON_MIN_G)

        peak_idx: list[int] = []
        for idx in range(1, smoothed.size - 1):
            amp = float(smoothed[idx])
            if amp < threshold:
                continue
            if amp > float(smoothed[idx - 1]) and amp >= float(smoothed[idx + 1]):
                peak_idx.append(idx)

        if not peak_idx:
            if smoothed.size > 1:
                candidate = int(np.argmax(smoothed[1:]) + 1)
            else:
                candidate = int(np.argmax(smoothed))
            if candidate >= 0 and float(smoothed[candidate]) > 0:
                peak_idx = [candidate]

        peak_idx.sort(key=lambda idx: float(smoothed[idx]), reverse=True)
        peaks: list[dict[str, float]] = []
        for idx in peak_idx[:top_n]:
            raw_amp = float(amps[idx])
            peaks.append(
                {
                    "hz": float(freqs[idx]),
                    "amp": raw_amp,
                    "snr_ratio": (raw_amp + 1e-9) / (floor_amp + 1e-9),
                }
            )
        return peaks

    def _fft_params(self, sample_rate_hz: int) -> tuple[np.ndarray, np.ndarray]:
        cached = self._fft_cache.get(sample_rate_hz)
        if cached is not None:
            return cached
        if sample_rate_hz <= 0:
            empty = np.empty(0, dtype=np.float32)
            return empty, np.empty(0, dtype=np.intp)
        freqs = np.fft.rfftfreq(self.fft_n, d=1.0 / sample_rate_hz)
        valid = freqs <= self.spectrum_max_hz
        freq_slice = freqs[valid].astype(np.float32)
        valid_idx = np.flatnonzero(valid)
        self._fft_cache[sample_rate_hz] = (freq_slice, valid_idx)
        if len(self._fft_cache) > self._fft_cache_maxsize:
            oldest = next(iter(self._fft_cache))
            del self._fft_cache[oldest]
        return freq_slice, valid_idx

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
            time_window = self._medfilt3(time_window)
        time_window_detrended = time_window - np.mean(time_window, axis=1, keepdims=True)

        metrics: dict[str, Any] = {}
        for axis_idx, axis in enumerate(AXES):
            axis_data = time_window_detrended[axis_idx]
            if axis_data.size == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(axis_data), dtype=np.float64)))
            p2p = float(np.max(axis_data) - np.min(axis_data))
            metrics[axis] = {
                "rms": rms,
                "p2p": p2p,
                "peaks": [],
            }

        if time_window_detrended.size > 0:
            vib_mag = np.sqrt(np.sum(np.square(time_window_detrended, dtype=np.float64), axis=0))
            vib_mag_rms = float(np.sqrt(np.mean(np.square(vib_mag), dtype=np.float64)))
            vib_mag_p2p = float(np.max(vib_mag) - np.min(vib_mag))
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
            axis_amp_slices = fft_result["axis_amp_slices"]

            for axis in fft_result["axis_peaks"]:
                metrics.setdefault(axis, {"rms": 0.0, "p2p": 0.0, "peaks": []})
                metrics[axis]["peaks"] = fft_result["axis_peaks"][axis]

            if axis_amp_slices:
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
            if buf is not None:
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
                buf.cached_spectrum_payload = None
                buf.cached_spectrum_payload_generation = -1
                buf.cached_selected_payload = None
                buf.cached_selected_payload_key = None
        self._last_compute_duration_s = time.monotonic() - t0
        self._total_compute_calls += 1
        return metrics

    def _compute_fft_spectrum(
        self,
        fft_block: np.ndarray,
        sample_rate_hz: int,
    ) -> dict[str, Any]:
        """Shared FFT spectrum computation used by both compute_metrics and debug_spectrum.

        Returns a dict with keys: freq_slice, valid_idx, spectrum_by_axis,
        axis_amp_slices, axis_amps, combined_amp, strength_metrics, axis_peaks.
        """
        if self._spike_filter_enabled:
            fft_block = self._medfilt3(fft_block)
        fft_block = fft_block - np.mean(fft_block, axis=1, keepdims=True)
        freq_slice, valid_idx = self._fft_params(sample_rate_hz)
        spectrum_by_axis: dict[str, dict[str, np.ndarray]] = {}
        axis_amp_slices: list[np.ndarray] = []
        axis_amps: dict[str, np.ndarray] = {}
        axis_peaks: dict[str, list] = {}

        for axis_idx, axis in enumerate(AXES):
            windowed = fft_block[axis_idx] * self._fft_window
            spec = np.abs(np.fft.rfft(windowed)).astype(np.float32)
            spec *= self._fft_scale
            if spec.size > 0:
                spec[0] *= 0.5
            if (self.fft_n % 2) == 0 and spec.size > 1:
                spec[-1] *= 0.5
            amp_slice = spec[valid_idx]
            amp_for_peaks = amp_slice.copy()
            if amp_for_peaks.size > 1:
                amp_for_peaks[0] = 0.0
            axis_peaks[axis] = self._top_peaks(
                freq_slice,
                amp_for_peaks,
                top_n=3,
                smoothing_bins=3,
            )
            spectrum_by_axis[axis] = {
                "freq": freq_slice,
                "amp": amp_slice,
            }
            axis_amps[axis] = amp_slice
            axis_amp_slices.append(amp_for_peaks)

        combined_amp = np.empty(0, dtype=np.float32)
        strength_metrics: dict[str, Any] = {}
        if axis_amp_slices:
            combined_amp = np.asarray(
                combined_spectrum_amp_g(
                    axis_spectra_amp_g=axis_amp_slices,  # type: ignore[arg-type]
                    axis_count_for_mean=len(axis_amp_slices),
                ),
                dtype=np.float32,
            )
            strength_metrics = compute_vibration_strength_db(
                freq_hz=self._float_list(freq_slice),
                combined_spectrum_amp_g_values=self._float_list(combined_amp),
                peak_bandwidth_hz=PEAK_BANDWIDTH_HZ,
                peak_separation_hz=PEAK_SEPARATION_HZ,
                top_n=5,
            )

        return {
            "freq_slice": freq_slice,
            "valid_idx": valid_idx,
            "spectrum_by_axis": spectrum_by_axis,
            "axis_amp_slices": axis_amp_slices,
            "axis_amps": axis_amps,
            "combined_amp": combined_amp,
            "strength_metrics": strength_metrics,
            "axis_peaks": axis_peaks,
        }

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
            "x": self._float_list(buf.latest_spectrum.get("x", {}).get("amp", _empty)),
            "y": self._float_list(buf.latest_spectrum.get("y", {}).get("amp", _empty)),
            "z": self._float_list(buf.latest_spectrum.get("z", {}).get("amp", _empty)),
            "combined_spectrum_amp_g": (
                self._float_list(buf.latest_spectrum.get("combined", {}).get("amp", _empty))
            ),
            "strength_metrics": dict(buf.latest_strength_metrics),
        }
        buf.cached_spectrum_payload = payload
        buf.cached_spectrum_payload_generation = buf.spectrum_generation
        return payload

    @_synchronized
    def multi_spectrum_payload(self, client_ids: list[str]) -> dict[str, Any]:
        shared_freq: np.ndarray | None = None
        clients: dict[str, dict[str, list[float]]] = {}
        mismatch_ids: list[str] = []

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
            client_payload = self.spectrum_payload(client_id)
            client_payload["freq"] = self._float_list(client_freq)
            clients[client_id] = client_payload

            tr = self._analysis_time_range(buf)
            if tr is not None:
                ranges.append((client_id, tr[0], tr[1]))
                if tr[2]:
                    any_synced = True
                else:
                    all_synced = False

        payload: dict[str, Any] = {
            "freq": self._float_list(shared_freq) if shared_freq is not None else [],
            "clients": clients,
        }
        if mismatch_ids:
            payload["warning"] = {
                "code": "frequency_bin_mismatch",
                "message": "Per-client frequency axes returned due to sample-rate mismatch.",
                "client_ids": sorted(mismatch_ids),
            }
            payload["freq"] = []

        # --- Alignment metadata ----------------------------------------------
        if len(ranges) >= 2:
            shared_start = max(s for _, s, _ in ranges)
            shared_end = min(e for _, _, e in ranges)
            overlap = max(0.0, shared_end - shared_start)
            union_start = min(s for _, s, _ in ranges)
            union_end = max(e for _, _, e in ranges)
            # Guard against zero-division with a tiny epsilon.
            union = max(1e-9, union_end - union_start)
            overlap_ratio = overlap / union
            payload["alignment"] = {
                "overlap_ratio": round(overlap_ratio, 4),
                "aligned": overlap_ratio >= _ALIGNMENT_MIN_OVERLAP,
                "shared_window_s": round(overlap, 4),
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

        waveform = {"t": self._float_list(x)}
        for axis_idx, axis in enumerate(AXES):
            waveform[axis] = self._float_list(decimated[axis_idx])

        spectrum: dict[str, Any] = {}
        if buf.latest_spectrum:
            x_axis = buf.latest_spectrum.get("x", {})
            freq = x_axis.get("freq", np.array([], dtype=np.float32))
            spectrum["freq"] = self._float_list(freq)
            for axis in AXES:
                axis_data = buf.latest_spectrum.get(axis, {})
                _empty = np.array([], dtype=np.float32)
                spectrum[axis] = self._float_list(axis_data.get("amp", _empty))
            combined = buf.latest_spectrum.get("combined")
            spectrum["combined_spectrum_amp_g"] = (
                self._float_list(combined["amp"])
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
            "x": self._float_list(block[0]),
            "y": self._float_list(block[1]),
            "z": self._float_list(block[2]),
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
        stale_ids = [
            client_id for client_id in self._buffers.keys() if client_id not in keep_client_ids
        ]
        for client_id in stale_ids:
            self._buffers.pop(client_id, None)

    def intake_stats(self) -> dict[str, Any]:
        """Return lightweight intake/analysis metrics for observability."""
        return {
            "total_ingested_samples": self._total_ingested_samples,
            "total_compute_calls": self._total_compute_calls,
            "last_compute_duration_s": self._last_compute_duration_s,
        }

    # -- Time-alignment helpers ------------------------------------------------

    def _analysis_time_range(self, buf: ClientBuffer) -> tuple[float, float, bool] | None:
        """Return ``(start_s, end_s, synced)`` for the current analysis window.

        When the sensor has reported a ``t0_us`` (set by ``CMD_SYNC_CLOCK``),
        the range is derived from the *sensor* timestamp which is already in
        server-relative microseconds — this is precise.  Otherwise the range
        is estimated from the server-side ``last_ingest_mono_s``.

        The third element *synced* is ``True`` when ``t0_us``-based alignment
        is in use.

        Returns ``None`` when the buffer has no data or no timing information.
        """
        if buf.count == 0 or buf.last_ingest_mono_s <= 0:
            return None
        sr = buf.sample_rate_hz or self.sample_rate_hz
        if sr <= 0:
            return None
        desired = int(max(1, float(sr) * float(self.waveform_seconds)))
        n_window = min(buf.count, buf.capacity, desired)
        duration_s = float(n_window) / float(sr)

        if buf.last_t0_us > 0:
            # Sensor-clock path (precise, after CMD_SYNC_CLOCK).
            # last_t0_us marks the *first sample* in the most recently
            # ingested frame.  Advance by the samples in that frame to
            # approximate the newest sample time.
            end_us = buf.last_t0_us + (buf.samples_since_t0 * 1_000_000) // max(1, sr)
            end_s = float(end_us) / 1_000_000.0
            start_s = end_s - duration_s
            return (start_s, end_s, True)

        # Fallback: server arrival time.
        end = buf.last_ingest_mono_s
        start = end - duration_s
        return (start, end, False)

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

        # Shared window = intersection of all ranges.
        shared_start = max(s for s, _ in ranges)
        shared_end = min(e for _, e in ranges)
        overlap = max(0.0, shared_end - shared_start)

        # Union span (earliest start → latest end).
        # Guard against zero-division with a tiny epsilon.
        union_start = min(s for s, _ in ranges)
        union_end = max(e for _, e in ranges)
        union = max(1e-9, union_end - union_start)

        overlap_ratio = overlap / union
        # Aligned if at least 50 % of the union is covered by the intersection.
        aligned = overlap_ratio >= _ALIGNMENT_MIN_OVERLAP

        shared: dict[str, float] | None = None
        if overlap > 0:
            shared = {
                "start_s": shared_start,
                "end_s": shared_end,
                "duration_s": overlap,
            }

        return {
            "per_sensor": per_sensor,
            "shared_window": shared,
            "overlap_ratio": round(overlap_ratio, 4),
            "aligned": aligned,
            "clock_synced": all_synced,
            "sensors_included": included,
            "sensors_excluded": excluded,
        }
