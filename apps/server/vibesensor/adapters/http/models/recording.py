"""Recording-status HTTP API models."""

from __future__ import annotations

from pydantic import BaseModel


class RecordingStatusResponse(BaseModel):
    """Response body with the current recording (run-logging) status."""

    enabled: bool
    run_id: str | None
    write_error: str | None
    analysis_in_progress: bool
    start_time_utc: str | None = None
    samples_written: int = 0
    samples_dropped: int = 0
    last_completed_run_id: str | None = None
    last_completed_run_error: str | None = None
