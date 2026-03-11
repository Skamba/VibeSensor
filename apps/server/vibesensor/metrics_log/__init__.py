"""Metrics recording package.

- :mod:`~vibesensor.metrics_log.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.metrics_log.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager.
- :mod:`~vibesensor.metrics_log.logger` — ``MetricsLogger``: the
  façade that coordinates recording lifecycle, session state, and
  history-DB persistence.
"""

from .logger import (
    MetricsLogger,
    MetricsLoggerConfig,
    MetricsShutdownReport,
)

__all__ = [
    "MetricsLogger",
    "MetricsLoggerConfig",
    "MetricsShutdownReport",
]
