"""Signal processing package.

This package contains the core vibration signal processing pipeline:

- :mod:`~vibesensor.processing.buffers` — per-client circular buffer storage.
- :mod:`~vibesensor.processing.fft` — pure FFT / spectral-analysis functions.
- :mod:`~vibesensor.processing.time_align` — multi-sensor time-alignment utilities.
- :mod:`~vibesensor.processing.processor` — the stateful :class:`SignalProcessor`
  coordinator that ties everything together.

All public symbols are re-exported here so that existing
``from vibesensor.processing import SignalProcessor`` (and similar) imports
continue to work without changes.

The underscore-prefixed names (``_compute_overlap``,
``_ALIGNMENT_MIN_OVERLAP``) are retained for
backward compatibility — they were module-level names in the original
single-file ``processing.py`` and are imported by existing test code.
"""

from .buffers import ClientBuffer  # noqa: F401
from .processor import (
    MAX_CLIENT_SAMPLE_RATE_HZ,  # noqa: F401
    SignalProcessor,  # noqa: F401
)
from .time_align import (
    _ALIGNMENT_MIN_OVERLAP,  # noqa: F401
)
from .time_align import (
    compute_overlap as _compute_overlap,  # noqa: F401
)

__all__ = [
    "ClientBuffer",
    "MAX_CLIENT_SAMPLE_RATE_HZ",
    "SignalProcessor",
    "_ALIGNMENT_MIN_OVERLAP",
    "_compute_overlap",
]
