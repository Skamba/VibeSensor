"""Metrics recording package.

- :mod:`~vibesensor.use_cases.run.lifecycle_state` — ``RunLifecycleState``:
  in-memory recording-session state and transitions.
- :mod:`~vibesensor.use_cases.run.persistence_writer` —
  ``RunPersistenceWriter``: history-write coordination and retry/backoff
  bookkeeping above the injected persistence port.
- :mod:`~vibesensor.use_cases.run.sample_flush` —
  ``SampleFlushOrchestrator``: sample-building, flush, and auto-stop logic.
- :mod:`~vibesensor.use_cases.run.status_reporting` — focused status and
  health payload helpers used by ``RunRecorder``.
- :mod:`~vibesensor.use_cases.run.sample_builder` — pure functions for
  building sample records from sensor metrics.
- :mod:`~vibesensor.use_cases.run._recorder_types` — recorder configuration
  and shutdown-report helpers shared around ``RunRecorder``.
- :mod:`~vibesensor.use_cases.run._recorder_runtime` — periodic loop and
  recorder-runtime helpers shared around ``RunRecorder``.
- :mod:`~vibesensor.use_cases.run.post_analysis` — ``PostAnalysisWorker``:
  background analysis thread/queue manager and health surface.
- :mod:`~vibesensor.use_cases.run.post_analysis_loader` — focused run
  metadata/sample loading plus bounded sampling for post-analysis.
- :mod:`~vibesensor.use_cases.run.post_analysis_executor` — execution/writeback
  coordination with explicit result outcomes for post-analysis runs.
- :mod:`~vibesensor.use_cases.run.post_analysis_summary` — persisted-analysis
  building over diagnostics results and sampling metadata.
- :mod:`~vibesensor.use_cases.run.logger` — ``RunRecorder``: single
  coordinator that owns the recording lifecycle plus delegation to the
  focused helpers above.
"""

from ._recorder_types import RecorderShutdownReport, RunRecorderConfig
from .logger import RunRecorder

__all__ = [
    "RunRecorder",
    "RunRecorderConfig",
    "RecorderShutdownReport",
]
