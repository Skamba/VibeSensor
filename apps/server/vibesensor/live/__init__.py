"""Live telemetry: signal processing, the processing loop, and the WebSocket broadcaster.

- :mod:`~vibesensor.live.processor` — :class:`SignalProcessor`, the owner of
  per-client buffers, ingest, snapshot → compute → commit, and read views.
- :mod:`~vibesensor.live.buffers` — :class:`ClientBuffer` ring buffer and its
  in-place mutations (append, resize, reset, metric commit).
- :mod:`~vibesensor.live.compute` — metrics/FFT computation from immutable
  snapshots.
- :mod:`~vibesensor.live.payload` — live ``spectra`` payload builder.
- :mod:`~vibesensor.live.time_align` — multi-sensor time-alignment helpers.
- :mod:`~vibesensor.live.processing_loop` — the periodic metrics/FFT tick.
- :mod:`~vibesensor.live.ws_payload_projection` /
  :mod:`~vibesensor.live.broadcaster` — live WebSocket payload and push loop.
"""
