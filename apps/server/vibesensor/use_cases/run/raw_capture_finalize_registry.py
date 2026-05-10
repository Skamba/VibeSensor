"""Raw-capture finalization bookkeeping for recording runs."""

from __future__ import annotations

import logging

from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.types.raw_capture import RawCaptureManifest
from vibesensor.shared.types.run_schema import RunRawCaptureFinalize
from vibesensor.use_cases.run.raw_capture_writer import RawCaptureFinalizeResult

__all__ = ["RawCaptureFinalizeRegistry"]


class RawCaptureFinalizeRegistry:
    """Store raw-capture finalize results and manifests by run."""

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger
        self._manifests: dict[str, RawCaptureManifest] = {}
        self._results: dict[str, RunRawCaptureFinalize] = {}

    def manifest_for_run(self, run_id: str) -> RawCaptureManifest | None:
        return self._manifests.get(run_id)

    def finalize_for_run(self, run_id: str) -> RunRawCaptureFinalize | None:
        return self._results.get(run_id)

    def record_result(
        self,
        run_id: str,
        result: RawCaptureFinalizeResult,
    ) -> RunRawCaptureFinalize:
        finalized = RunRawCaptureFinalize(
            status=result.status,
            queue_depth=result.queue_depth,
            error_summary=result.error,
        )
        self._results[run_id] = finalized
        if result.manifest is not None:
            self._manifests[run_id] = result.manifest
        if result.completed or result.status == "not_configured":
            return finalized
        self._logger.warning(
            "raw_capture_finalize_degraded",
            extra=log_extra(
                event="raw_capture_finalize_degraded",
                run_id=run_id,
                raw_capture_finalize_status=result.status,
                raw_capture_queue_depth=result.queue_depth,
                raw_capture_error=result.error,
            ),
        )
        return finalized

    def record_late_result(
        self,
        run_id: str,
        result: RawCaptureFinalizeResult,
    ) -> RunRawCaptureFinalize | None:
        previous = self._results.get(run_id)
        if previous is not None and previous.status != "timeout":
            return None
        return self.record_result(run_id, result)
