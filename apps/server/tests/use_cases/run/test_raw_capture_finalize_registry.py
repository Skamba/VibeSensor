from __future__ import annotations

import logging

from vibesensor.use_cases.run.raw_capture_finalize_registry import RawCaptureFinalizeRegistry
from vibesensor.use_cases.run.raw_capture_writer import RawCaptureFinalizeResult


def test_raw_capture_finalize_registry_keeps_success_over_late_duplicate(
    caplog,
) -> None:
    registry = RawCaptureFinalizeRegistry(logger=logging.getLogger("test.raw.finalize"))

    with caplog.at_level(logging.WARNING, logger="test.raw.finalize"):
        first = registry.record_result("run-1", RawCaptureFinalizeResult(status="completed"))
        ignored = registry.record_late_result(
            "run-1",
            RawCaptureFinalizeResult(status="completed", error="late duplicate"),
        )

    assert first.status == "completed"
    assert ignored is None
    assert registry.finalize_for_run("run-1") == first
    assert not caplog.records


def test_raw_capture_finalize_registry_replaces_timeout_with_late_result() -> None:
    registry = RawCaptureFinalizeRegistry(logger=logging.getLogger("test.raw.finalize"))

    timeout = registry.record_result(
        "run-2",
        RawCaptureFinalizeResult(status="timeout", error="pending", queue_depth=2),
    )
    completed = registry.record_late_result(
        "run-2",
        RawCaptureFinalizeResult(status="completed", queue_depth=0),
    )

    assert timeout.status == "timeout"
    assert completed is not None
    assert completed.status == "completed"
    assert registry.finalize_for_run("run-2") == completed
