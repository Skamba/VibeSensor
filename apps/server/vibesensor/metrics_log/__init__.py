"""Metrics recording package.

This package contains the metrics recording pipeline split into focused
modules:

- :mod:`~vibesensor.metrics_log.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.metrics_log.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager.
- :mod:`~vibesensor.metrics_log.logger` — ``MetricsLogger``: the
  façade that coordinates recording lifecycle, session state, and
  history-DB persistence.

All public symbols are re-exported here so that existing
``from vibesensor.metrics_log import MetricsLogger`` (and similar)
imports continue to work without changes.
"""

from .logger import (
    LoggingStatusPayload,
    MetricsLogger,
    MetricsLoggerConfig,
    MetricsShutdownReport,
)
from .post_analysis import (
    PostAnalysisWorker,
)
from .sample_builder import (
    build_run_metadata,
    build_sample_records,
    dominant_hz_from_strength,
    extract_strength_data,
    firmware_version_for_run,
    resolve_speed_context,
    safe_metric,
)

__all__ = [
    "LoggingStatusPayload",
    "MetricsLogger",
    "MetricsLoggerConfig",
    "MetricsShutdownReport",
    "PostAnalysisWorker",
    "build_run_metadata",
    "build_sample_records",
    "dominant_hz_from_strength",
    "extract_strength_data",
    "firmware_version_for_run",
    "resolve_speed_context",
    "safe_metric",
]
