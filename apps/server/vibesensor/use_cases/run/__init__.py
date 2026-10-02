"""Metrics recording package.

- :mod:`~vibesensor.recording.lifecycle_state` — ``RunLifecycleState``:
  in-memory recording-session state and transitions.
- :mod:`~vibesensor.recording.persistence_writer` —
  ``RunPersistenceWriter``: history-write coordination and retry/backoff
  bookkeeping above the injected persistence port.
- :mod:`~vibesensor.recording.sample_flush` —
  ``SampleFlushOrchestrator``: sample-building, flush, and auto-stop logic.
- :mod:`~vibesensor.recording.status_reporting` — focused status and
  health payload helpers used by ``RunRecorder``.
- :mod:`~vibesensor.recording.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.recording._recorder_types` — recorder configuration
  and shutdown-report helpers shared around ``RunRecorder``.
- :mod:`~vibesensor.recording._recorder_runtime` — periodic loop and
  recorder-runtime helpers shared around ``RunRecorder``.
- :mod:`~vibesensor.use_cases.run.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager and health surface.
- :mod:`~vibesensor.use_cases.run.post_analysis_loader` — focused run
  metadata/sample loading plus bounded sampling for post-analysis.
- :mod:`~vibesensor.use_cases.run.post_analysis_executor` — execution/writeback
  coordination with explicit result outcomes for post-analysis runs.
- :mod:`~vibesensor.use_cases.run.post_analysis_summary` — persisted-analysis
  building over diagnostics results and sampling metadata.
- :mod:`~vibesensor.recording.recorder` — ``RunRecorder``: single
  coordinator that owns the recording lifecycle plus delegation to the
  focused helpers above.
"""
