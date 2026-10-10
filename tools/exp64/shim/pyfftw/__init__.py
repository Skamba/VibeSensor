"""Experiment-only stand-in for pyFFTW (no cp314t wheel): scipy.fft float32 rfft into the output array."""
import numpy as np
from scipy import fft as _fft


def empty_aligned(shape, dtype):
    return np.empty(shape, dtype=dtype)


class FFTW:
    def __init__(self, input_array, output_array, axes=(-1,), direction="FFTW_FORWARD", flags=(), threads=1):
        self.input_array = input_array
        self.output_array = output_array
        self._axis = axes[0]

    def __call__(self):
        self.output_array[...] = _fft.rfft(self.input_array, axis=self._axis, workers=1)
        return self.output_array
