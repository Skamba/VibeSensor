"""Raw-capture replay helpers for post-stop analysis."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from vibesensor.domain.strength_metrics import StrengthMetrics
from vibesensor.shared.boundaries.codecs import strength_metrics_from_mapping
from vibesensor.shared.constants.dsp import SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.shared.types.raw_capture import RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.vibration_strength import combined_spectrum_amp_g, compute_vibration_strength_db

__all__ = ["build_raw_backed_samples"]


def build_raw_backed_samples(
    *,
    samples: tuple[SensorFrame, ...],
    metadata: RunMetadata,
    raw_capture: RawRunCapture | None,
) -> tuple[tuple[SensorFrame, ...], int]:
    """Replace summary strength metrics with raw-backed metrics when possible."""

    if raw_capture is None:
        return samples, 0
    fft_n = int(metadata.fft_window_size_samples or 0)
    if fft_n <= 0:
        return samples, 0
    replayed: list[SensorFrame] = []
    raw_backed_count = 0
    scale = metadata.accel_scale_g_per_lsb
    for sample in samples:
        rebuilt = _rebuild_sample(
            sample=sample,
            raw_capture=raw_capture,
            fft_n=fft_n,
            accel_scale_g_per_lsb=scale,
        )
        if rebuilt is not sample:
            raw_backed_count += 1
        replayed.append(rebuilt)
    return tuple(replayed), raw_backed_count


def _rebuild_sample(
    *,
    sample: SensorFrame,
    raw_capture: RawRunCapture,
    fft_n: int,
    accel_scale_g_per_lsb: float | None,
) -> SensorFrame:
    sensor_data = raw_capture.sensor_data(sample.client_id)
    if sensor_data is None:
        return sample
    sample_rate_hz = int(sample.sample_rate_hz or sensor_data.manifest.sample_rate_hz or 0)
    if sample_rate_hz <= 0:
        return sample
    target_end = _target_end_index(
        t_s=sample.t_s,
        sample_rate_hz=sample_rate_hz,
        available_samples=sensor_data.samples_i16.shape[0],
    )
    if target_end is None or target_end < fft_n:
        return sample
    window_i16 = sensor_data.samples_i16[target_end - fft_n : target_end]
    if window_i16.shape[0] != fft_n:
        return sample
    window_f32 = window_i16.astype(np.float32, copy=True)
    if accel_scale_g_per_lsb is not None and accel_scale_g_per_lsb > 0:
        window_f32 *= np.float32(accel_scale_g_per_lsb)
    domain_strength = _compute_strength_metrics(window_f32, sample_rate_hz)
    top_peaks = tuple(peak for peak in domain_strength.top_peaks if peak.is_valid)
    last_xyz = window_f32[-1]
    return replace(
        sample,
        accel_x_g=float(last_xyz[0]),
        accel_y_g=float(last_xyz[1]),
        accel_z_g=float(last_xyz[2]),
        dominant_freq_hz=domain_strength.dominant_hz,
        top_peaks=top_peaks,
        vibration_strength_db=domain_strength.vibration_strength_db,
        strength_bucket=domain_strength.strength_bucket,
        strength_peak_amp_g=domain_strength.peak_amp_g,
        strength_floor_amp_g=domain_strength.noise_floor_amp_g,
    )


def _target_end_index(
    *,
    t_s: float | None,
    sample_rate_hz: int,
    available_samples: int,
) -> int | None:
    if available_samples <= 0:
        return None
    if t_s is None or t_s <= 0:
        return None
    target = int(round(float(t_s) * float(sample_rate_hz)))
    if target <= 0:
        return None
    return min(target, available_samples)


def _compute_strength_metrics(window_f32: np.ndarray, sample_rate_hz: int) -> StrengthMetrics:
    axes_by_time = window_f32.T
    detrended = axes_by_time - np.mean(axes_by_time, axis=1, keepdims=True, dtype=np.float32)
    fft_window = np.asarray(np.hanning(window_f32.shape[0]), dtype=np.float32)
    if fft_window.size <= 0:
        return strength_metrics_from_mapping(None)
    scale = float(2.0 / max(1.0, float(np.sum(fft_window))))
    transformed = np.fft.rfft(detrended * fft_window, axis=1)
    freqs = np.fft.rfftfreq(window_f32.shape[0], d=1.0 / sample_rate_hz)
    valid = (freqs >= SPECTRUM_MIN_HZ) & (freqs <= SPECTRUM_MAX_HZ)
    if not np.any(valid):
        return strength_metrics_from_mapping(None)
    axis_spectra = np.abs(transformed[:, valid]).astype(np.float64, copy=False) * scale
    combined = np.asarray(
        combined_spectrum_amp_g(axis_spectra_amp_g=axis_spectra, axis_count_for_mean=3),
        dtype=np.float64,
    )
    raw_strength = compute_vibration_strength_db(
        freq_hz=freqs[valid],
        combined_spectrum_amp_g_values=combined,
    )
    return strength_metrics_from_mapping(raw_strength)
