"""Metrics recording package.

This package contains the metrics recording pipeline split into focused
modules:

- :mod:`~vibesensor.metrics_log.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.metrics_log.session_state` — explicit recording-session
  lifecycle state.
- :mod:`~vibesensor.metrics_log.persistence` — history DB create/append/finalize
  coordination.
- :mod:`~vibesensor.metrics_log.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager.
- :mod:`~vibesensor.metrics_log.logger` — ``MetricsLogger``: the
  façade that coordinates the focused collaborators above.

All public symbols are re-exported here so that existing
``from vibesensor.metrics_log import MetricsLogger`` (and similar)
imports continue to work without changes.
"""

from .logger import (
    MetricsLogger,  # noqa: F401
    MetricsLoggerConfig,  # noqa: F401
    MetricsShutdownReport,  # noqa: F401
)
from .post_analysis import (
    PostAnalysisWorker,  # noqa: F401
)
from .sample_builder import (  # noqa: F401
    build_run_metadata,
    build_sample_records,
    dominant_hz_from_strength,
    extract_axis_top_peaks,
    extract_strength_data,
    firmware_version_for_run,
    resolve_speed_context,
    safe_metric,
)

__all__ = [
    "MetricsLogger",
    "MetricsLoggerConfig",
    "MetricsShutdownReport",
    "PostAnalysisWorker",
    "build_run_metadata",
    "build_sample_records",
    "dominant_hz_from_strength",
    "extract_axis_top_peaks",
    "extract_strength_data",
    "firmware_version_for_run",
    "resolve_speed_context",
    "safe_metric",
]
