"""Metrics recording package.

- :mod:`~vibesensor.use_cases.run.lifecycle_state` — ``RunLifecycleState``:
  in-memory recording-session state and transitions.
- :mod:`~vibesensor.use_cases.run.persistence_writer` —
  ``RunPersistenceWriter``: history-write coordination and retry/backoff
  bookkeeping above the injected persistence port.
- :mod:`~vibesensor.use_cases.run.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.use_cases.run.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager above the injected persistence,
  analysis, and error-state boundaries.
- :mod:`~vibesensor.use_cases.run.logger` — ``RunRecorder``: single
  coordinator that owns the recording loop plus delegation to persistence
  and post-analysis helpers.
"""

from .logger import (
    RecorderShutdownReport,
    RunRecorder,
    RunRecorderConfig,
)

__all__ = [
    "RunRecorder",
    "RunRecorderConfig",
    "RecorderShutdownReport",
]
