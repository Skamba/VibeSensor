"""Compatibility imports for shared FFT analysis primitives."""

from vibesensor.shared.fft_analysis import (
    AXES,
    compute_fft_spectrum,
    float_list,
    medfilt3,
    noise_floor,
)

__all__ = [
    "AXES",
    "compute_fft_spectrum",
    "float_list",
    "medfilt3",
    "noise_floor",
]
