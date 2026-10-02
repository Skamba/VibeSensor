"""Live signal processing.

- :mod:`~vibesensor.infra.processing.processor` — :class:`SignalProcessor`, the owner of
  per-client buffers, ingest, snapshot → compute → commit, and read views.
- :mod:`~vibesensor.infra.processing.buffers` — :class:`ClientBuffer` ring buffer and its
  in-place mutations (append, resize, reset, metric commit).
- :mod:`~vibesensor.infra.processing.compute` — metrics/FFT computation from immutable
  snapshots.
- :mod:`~vibesensor.infra.processing.payload` — live ``spectra`` payload builder.
- :mod:`~vibesensor.infra.processing.time_align` — multi-sensor time-alignment helpers.
- :mod:`~vibesensor.shared.fft_analysis` — shared FFTW-backed spectral-analysis
  functions reused by processing, replay, diagnostics, and reporting.
"""
