"""Run recording: the ``RunRecorder`` lifecycle, sample flush, raw capture, and run metadata.

- :mod:`~vibesensor.recording.recorder` — ``RunRecorder``: owns the recording
  lifecycle and delegates to the focused helpers below.
- :mod:`~vibesensor.recording.lifecycle_state` — in-memory session state.
- :mod:`~vibesensor.recording.persistence_writer` — history-write coordination
  and retry/backoff bookkeeping.
- :mod:`~vibesensor.recording.sample_flush` — sample building, flush, auto-stop.
- :mod:`~vibesensor.recording.raw_capture_writer` — raw-capture sidecar writer.
- :mod:`~vibesensor.recording.run_metadata` — persisted run-metadata codec.
"""
