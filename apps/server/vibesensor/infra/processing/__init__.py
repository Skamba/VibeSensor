"""Signal processing package.

This package contains the core vibration signal processing pipeline:

- :mod:`~vibesensor.infra.processing.buffer_capacity` — buffer capacity, overflow,
  and resize policy helpers.
- :mod:`~vibesensor.infra.processing.buffer_store` — shared buffer state, ingest, locking,
  and state snapshots.
- :mod:`~vibesensor.infra.processing.compute` — FFT cache/window ownership plus metric
  computation from immutable snapshots.
- :mod:`~vibesensor.infra.processing.snapshot_builder` — compute-snapshot caching and
  window-size helpers.
- :mod:`~vibesensor.shared.fft_analysis` — shared FFTW-backed spectral-analysis
  functions reused by processing, replay, diagnostics, and reporting.
- :mod:`~vibesensor.infra.processing.payload` — payload builders for spectrum,
  debug-spectrum, intake-stats, and time-alignment views.
- :mod:`~vibesensor.infra.processing.time_align` — multi-sensor time-alignment utilities.
- :mod:`~vibesensor.infra.processing.processor` — the stable :class:`SignalProcessor`
  facade that composes the subsystems above.

Re-exports public symbols for convenient access.
"""

from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.processor import (
    MAX_CLIENT_SAMPLE_RATE_HZ,
    SignalProcessor,
)

__all__ = [
    "MAX_CLIENT_SAMPLE_RATE_HZ",
    "ClientBuffer",
    "SignalProcessor",
]
