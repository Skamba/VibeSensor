from __future__ import annotations

# Do not implement math here; this file is legacy import compatibility only.

from .analysis.strength_metrics import (
    _median as _canonical_median,
    strength_db as _strength_db,
    strength_floor_amp_g as _strength_floor_amp_g,
    strength_peak_band_rms_amp_g as _strength_peak_band_rms_amp_g,
)

_median = _canonical_median


def compute_floor_rms(
    *,
    freq: list[float],
    values: list[float],
    peak_indexes: list[int],
    exclusion_hz: float,
    min_hz: float,
    max_hz: float,
) -> float:
    return _strength_floor_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        peak_indexes=peak_indexes,
        exclusion_hz=exclusion_hz,
        min_hz=min_hz,
        max_hz=max_hz,
    )


def compute_band_rms(
    *, freq: list[float], values: list[float], center_idx: int, bandwidth_hz: float
) -> float:
    return _strength_peak_band_rms_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        center_idx=center_idx,
        bandwidth_hz=bandwidth_hz,
    )


def strength_db_above_floor(*, band_rms: float, floor_rms: float) -> float:
    return _strength_db(
        strength_peak_band_rms_amp_g=band_rms,
        strength_floor_amp_g=floor_rms,
    )
