from __future__ import annotations

import numpy as np

from ..payload_types import (
    DebugSpectrumErrorPayload,
    DebugSpectrumPayload,
    DebugSpectrumStatsPayload,
    DebugSpectrumTopBinPayload,
    RawSamplesErrorPayload,
    RawSamplesPayload,
    SelectedClientPayload,
    SharedWindowPayload,
    SpectraPayload,
    SpectrumSeriesPayload,
    TimeAlignmentPayload,
    TimeAlignmentSensorPayload,
)
from .buffer_store import SignalBufferStore
from .buffers import ClientBuffer
from .compute import SignalMetricsComputer
from .payload import (
    _empty_spectrum_payload,
    build_multi_spectrum_payload,
    build_selected_payload,
    build_spectrum_payload,
)
from .time_align import analysis_time_range, compute_overlap


class SignalProcessorViews:
    """Build payload/debug views from shared buffer state and computed spectra."""

    def __init__(
        self,
        *,
        store: SignalBufferStore,
        metrics: SignalMetricsComputer,
    ) -> None:
        self._store = store
        self._metrics = metrics

    def spectrum_payload(self, client_id: str) -> SpectrumSeriesPayload:
        with self._store.lock:
            return self._spectrum_payload_unlocked(client_id)

    def multi_spectrum_payload(self, client_ids: list[str]) -> SpectraPayload:
        with self._store.lock:
            return build_multi_spectrum_payload(
                self._store.buffers,
                client_ids,
                spectrum_fn=self._spectrum_payload_unlocked,
                analysis_time_range_fn=self._analysis_time_range_unlocked,
            )

    def selected_payload(self, client_id: str) -> SelectedClientPayload:
        with self._store.lock:
            buf = self._store.buffers.get(client_id)
            if buf is None or buf.count == 0:
                sr = self._store.config.sample_rate_hz
                return {
                    "client_id": client_id,
                    "sample_rate_hz": sr,
                    "waveform": {},
                    "spectrum": {},
                    "metrics": {},
                }
            return build_selected_payload(
                buf,
                client_id,
                sample_rate_hz=self._store.config.sample_rate_hz,
                waveform_seconds=self._store.config.waveform_seconds,
                waveform_display_hz=self._store.config.waveform_display_hz,
                latest_fn=self._store.copy_latest,
            )

    def debug_spectrum(self, client_id: str) -> DebugSpectrumPayload | DebugSpectrumErrorPayload:
        request = self._store.debug_request(client_id)
        if request.fft_block is None:
            return {
                "error": "insufficient samples",
                "count": request.count,
                "fft_n": self._store.config.fft_n,
            }

        fft_block = request.fft_block
        raw_mean = fft_block.mean(axis=1).tolist()
        raw_std = fft_block.std(axis=1).tolist()
        raw_min = fft_block.min(axis=1).tolist()
        raw_max = fft_block.max(axis=1).tolist()

        fft_result = self._metrics.compute_fft_spectrum(fft_block, request.sample_rate_hz)
        freq_slice = fft_result["freq_slice"]
        axis_amps = fft_result["axis_amps"]
        combined_amp = fft_result["combined_amp"]
        strength_metrics = fft_result["strength_metrics"]
        detrended_std = (fft_block - fft_block.mean(axis=1, keepdims=True)).std(axis=1).tolist()

        sorted_idx = np.argsort(combined_amp)[::-1]
        top_bins: list[DebugSpectrumTopBinPayload] = []
        for index in sorted_idx[:10]:
            top_bins.append(
                {
                    "bin": int(index),
                    "freq_hz": float(freq_slice[index]),
                    "combined_amp_g": float(combined_amp[index]),
                    "x_amp_g": float(axis_amps["x"][index]),
                    "y_amp_g": float(axis_amps["y"][index]),
                    "z_amp_g": float(axis_amps["z"][index]),
                },
            )

        raw_stats: DebugSpectrumStatsPayload = {
            "mean_g": raw_mean,
            "std_g": raw_std,
            "min_g": raw_min,
            "max_g": raw_max,
        }
        return {
            "client_id": client_id,
            "sample_rate_hz": request.sample_rate_hz,
            "fft_n": self._store.config.fft_n,
            "fft_scale": self._metrics.fft_scale,
            "window": "hann",
            "spectrum_min_hz": self._store.config.spectrum_min_hz,
            "spectrum_max_hz": self._store.config.spectrum_max_hz,
            "freq_bins": len(freq_slice),
            "freq_resolution_hz": float(request.sample_rate_hz) / self._store.config.fft_n,
            "raw_stats": raw_stats,
            "detrended_std_g": detrended_std,
            "vibration_strength_db": float(strength_metrics.get("vibration_strength_db", 0)),
            "top_bins_by_amplitude": top_bins,
            "strength_peaks": list(strength_metrics.get("top_peaks", [])),
        }

    def raw_samples(
        self,
        client_id: str,
        *,
        n_samples: int = 2048,
    ) -> RawSamplesPayload | RawSamplesErrorPayload:
        return self._store.raw_samples(client_id, n_samples=n_samples)

    def time_alignment_info(self, client_ids: list[str]) -> TimeAlignmentPayload:
        with self._store.lock:
            per_sensor: dict[str, TimeAlignmentSensorPayload] = {}
            ranges: list[tuple[float, float]] = []
            included: list[str] = []
            excluded: list[str] = []
            all_synced = True

            for client_id in client_ids:
                buf = self._store.buffers.get(client_id)
                if buf is None:
                    excluded.append(client_id)
                    continue
                time_range = self._analysis_time_range_unlocked(buf)
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

    def analysis_time_range(self, buf: ClientBuffer) -> tuple[float, float, bool] | None:
        with self._store.lock:
            return self._analysis_time_range_unlocked(buf)

    def _spectrum_payload_unlocked(self, client_id: str) -> SpectrumSeriesPayload:
        buf = self._store.buffers.get(client_id)
        if buf is None:
            return _empty_spectrum_payload()
        return build_spectrum_payload(buf)

    def _analysis_time_range_unlocked(self, buf: ClientBuffer) -> tuple[float, float, bool] | None:
        sr = buf.sample_rate_hz or self._store.config.sample_rate_hz
        return analysis_time_range(
            count=buf.count,
            last_ingest_mono_s=buf.last_ingest_mono_s,
            sample_rate_hz=sr,
            waveform_seconds=self._store.config.waveform_seconds,
            capacity=buf.capacity,
            last_t0_us=buf.last_t0_us,
            samples_since_t0=buf.samples_since_t0,
        )
