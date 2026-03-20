"""Metrics recording package.

- :mod:`~vibesensor.use_cases.run.lifecycle_state` — ``RunLifecycleState``:
  in-memory recording-session state and transitions.
- :mod:`~vibesensor.use_cases.run.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.use_cases.run.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager.
- :mod:`~vibesensor.use_cases.run.logger` — ``RunRecorder``: single
  coordinator that owns the recording loop plus persistence and
  post-analysis coordination.
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
