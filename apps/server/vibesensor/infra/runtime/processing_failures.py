"""Typed failure categories for one processing tick."""

from __future__ import annotations

from enum import StrEnum

from vibesensor.shared.exceptions import ProcessingError

__all__ = ["ProcessingFailureCategory", "ProcessingTickFailure"]


class ProcessingFailureCategory(StrEnum):
    """Stable categories for operational processing-tick failures."""

    SYNC_CLOCK = "sync_clock"
    COMPUTE_ALL = "compute_all"
    EVICT_CLIENTS = "evict_clients"


class ProcessingTickFailure(ProcessingError):
    """Categorized operational processing-tick failure."""

    def __init__(self, category: ProcessingFailureCategory, cause: Exception) -> None:
        super().__init__(str(cause))
        self.category = category
        self.cause = cause
