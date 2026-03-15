"""Signal processing package.

This package contains the core vibration signal processing pipeline:

- :mod:`~vibesensor.infra.processing.buffer_store` — shared buffer state, ingest, locking,
  and state snapshots.
- :mod:`~vibesensor.infra.processing.compute` — FFT cache/window ownership plus metric
  computation from immutable snapshots.
- :mod:`~vibesensor.infra.processing.fft` — pure FFT / spectral-analysis functions.
- :mod:`~vibesensor.infra.processing.time_align` — multi-sensor time-alignment utilities.
- :mod:`~vibesensor.infra.processing.processor` — the stable :class:`SignalProcessor`
  facade that composes the subsystems above.

All public symbols are re-exported here so that existing
``from vibesensor.infra.processing import SignalProcessor`` (and similar) imports
continue to work without changes.
"""

from .buffers import ClientBuffer
from .processor import (
    MAX_CLIENT_SAMPLE_RATE_HZ,
    SignalProcessor,
)

__all__ = [
    "MAX_CLIENT_SAMPLE_RATE_HZ",
    "ClientBuffer",
    "SignalProcessor",
]
