"""Shared sample/strength metric helpers for diagnostics."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.analysis._types import Sample
from vibesensor.analysis.constants import MEMS_NOISE_FLOOR_G, MIN_ANALYSIS_FREQ_HZ
from vibesensor.domain.strength_metrics import StrengthPeak
from vibesensor.dsp.vibration_strength import percentile, vibration_strength_db_scalar


def _sensor_limit_g(sensor_model: object) -> float | None:
    if not isinstance(sensor_model, str):
        return None
    if "adxl345" in sensor_model.lower():
        return 16.0
    return None


def _primary_vibration_strength_db(sample: Sample) -> float | None:
    value = sample.vibration_strength_db
    return float(value) if value is not None else None


def _analysed_peaks(sample: Sample) -> list[StrengthPeak]:
    return [
        peak
        for peak in sample.top_peaks[:8]
        if peak.hz > 0 and peak.amp > 0 and peak.hz >= MIN_ANALYSIS_FREQ_HZ
    ]


def _sample_top_peaks(sample: Sample) -> list[tuple[float, float]]:
    return [(peak.hz, peak.amp) for peak in _analysed_peaks(sample)]


def _sample_peak_prominence_db(sample: Sample) -> float | None:
    """How far the sample's most prominent peak stands out of the spectrum around it (dB).

    A peak recorded without its local floor stands on the sample's overall floor.
    """
    overall_floor = sample.strength_floor_amp_g or 0.0
    return max(
        (
            vibration_strength_db_scalar(
                peak_band_rms_amp_g=peak.amp,
                floor_amp_g=(
                    peak.local_floor_amp_g if peak.local_floor_amp_g is not None else overall_floor
                ),
            )
            for peak in _analysed_peaks(sample)
        ),
        default=None,
    )


def _estimate_strength_floor_amp_g(sample: Sample) -> float | None:
    """Estimate per-sample floor amplitude."""
    floor_amp = sample.strength_floor_amp_g
    if floor_amp is not None and floor_amp > 0:
        return float(floor_amp)
    peak_amps = sorted(amp for _hz, amp in _sample_top_peaks(sample) if amp > 0)
    if len(peak_amps) < 3:
        return None
    floor_from_peaks = float(percentile(peak_amps, 0.20))
    return float(floor_from_peaks) if floor_from_peaks > 0 else None


def _run_noise_baseline_g(samples: Sequence[Sample]) -> float | None:
    """Estimate run-level noise baseline as median of per-sample floor estimates."""
    floors: list[float] = []
    for sample in samples:
        floor_amp = _estimate_strength_floor_amp_g(sample)
        if floor_amp is not None:
            floors.append(floor_amp)
    if not floors:
        return None
    return float(percentile(sorted(floors), 0.50))


def _effective_baseline_floor(
    run_noise_baseline_g: float | None,
    *,
    extra_fallback: float | None = None,
) -> float:
    """Return a safe noise-floor value for SNR computations."""
    val = (
        run_noise_baseline_g
        if run_noise_baseline_g is not None
        else (extra_fallback if extra_fallback is not None else 0.0)
    )
    return float(max(float(MEMS_NOISE_FLOOR_G), float(val)))
