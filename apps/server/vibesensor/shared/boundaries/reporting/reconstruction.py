"""Report-focused reconstruction entrypoints for canonical projectable payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from vibesensor.shared.boundaries.reporting.summary import require_projectable_report_payload
from vibesensor.shared.boundaries.test_run_reconstruction import (
    test_run_from_persisted_analysis,
    test_run_from_summary,
)
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis

if TYPE_CHECKING:
    from vibesensor.domain import TestRun

__all__ = [
    "report_test_run_from_persisted_analysis",
    "report_test_run_from_summary",
]


def report_test_run_from_summary(payload: Mapping[str, object]) -> TestRun:
    """Rebuild the report domain aggregate from one canonical projectable payload."""
    require_projectable_report_payload(payload)
    return test_run_from_summary(payload)


def report_test_run_from_persisted_analysis(analysis: PersistedAnalysis) -> TestRun:
    """Rebuild the report domain aggregate from persisted analysis payloads."""
    require_projectable_report_payload(analysis)
    return test_run_from_persisted_analysis(analysis)
