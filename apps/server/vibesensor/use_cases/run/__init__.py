"""Metrics recording package.

- :mod:`~vibesensor.use_cases.run.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.use_cases.run.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager.
- :mod:`~vibesensor.use_cases.run.logger` — ``RunRecorder``: single
  class that owns recording lifecycle, session state, and
  history-DB persistence inline.
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
