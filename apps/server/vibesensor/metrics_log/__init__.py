"""Metrics recording package.

- :mod:`~vibesensor.metrics_log.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.metrics_log.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager.
- :mod:`~vibesensor.metrics_log.logger` — ``RunRecorder``: single
  class that owns recording lifecycle, session state, and
  history-DB persistence inline.
"""

from .logger import (
    MetricsShutdownReport,
    RunRecorder,
    RunRecorderConfig,
)

__all__ = [
    "RunRecorder",
    "RunRecorderConfig",
    "MetricsShutdownReport",
]
