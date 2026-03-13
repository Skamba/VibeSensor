"""A persisted run with its analysis results.

``HistoryRecord`` is the primary domain object for a completed or
in-progress run stored in the history database.  The
``HistoryRunPayload`` and ``HistoryRunListEntryPayload`` TypedDicts in
``backend_types`` remain as API transport adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "HistoryRecord",
]


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    """A persisted run with its analysis results.

    This is the primary domain object for a completed or in-progress run
    stored in the history database.  The ``HistoryRunPayload`` and
    ``HistoryRunListEntryPayload`` TypedDicts in ``backend_types`` remain
    as API transport adapters.
    """

    run_id: str
    status: str = ""
    start_time_utc: str = ""
    end_time_utc: str | None = None
    sample_count: int = 0
    error_message: str | None = None

    # -- queries -----------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"

    @property
    def is_recording(self) -> bool:
        return self.status == "recording"

    @property
    def has_error(self) -> bool:
        return self.status == "error"

    @property
    def is_analyzable(self) -> bool:
        """Whether this record can be (re)analyzed."""
        return self.status in ("complete", "error") and self.sample_count > 0

    @property
    def has_analysis(self) -> bool:
        """Whether analysis has been completed for this record."""
        return self.status == "complete"

    @property
    def display_status(self) -> str:
        """Human-readable status text."""
        labels = {
            "recording": "Recording",
            "complete": "Complete",
            "error": "Error",
            "stopped": "Stopped",
            "analyzing": "Analyzing",
        }
        return labels.get(self.status, self.status.title() if self.status else "Unknown")
