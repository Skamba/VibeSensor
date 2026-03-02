"""Metrics recording package.

This package contains the metrics recording pipeline split into focused
modules:

- :mod:`~vibesensor.metrics_log.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.metrics_log.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager.
- :mod:`~vibesensor.metrics_log.logger` — ``MetricsLogger``: the
  orchestrator that ties session lifecycle, persistence, and the live
  sample buffer together.

All public symbols are re-exported here so that existing
``from vibesensor.metrics_log import MetricsLogger`` (and similar)
imports continue to work without changes.
"""

from .logger import (
    _MAX_HISTORY_CREATE_RETRIES,  # noqa: F401
    MetricsLogger,  # noqa: F401
)
from .post_analysis import (
    _MAX_POST_ANALYSIS_SAMPLES,  # noqa: F401
    PostAnalysisWorker,  # noqa: F401
)
from .sample_builder import (  # noqa: F401
    _LIVE_SAMPLE_WINDOW_S,
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
    "PostAnalysisWorker",
    "_MAX_HISTORY_CREATE_RETRIES",
    "_MAX_POST_ANALYSIS_SAMPLES",
    "_LIVE_SAMPLE_WINDOW_S",
    "build_run_metadata",
    "build_sample_records",
    "dominant_hz_from_strength",
    "extract_axis_top_peaks",
    "extract_strength_data",
    "firmware_version_for_run",
    "resolve_speed_context",
    "safe_metric",
]
