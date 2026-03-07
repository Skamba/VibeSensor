"""Shared run-history constants for HistoryDB."""

from __future__ import annotations


class RunStatus:
    """String constants for the ``runs.status`` column."""

    RECORDING: str = "recording"
    ANALYZING: str = "analyzing"
    COMPLETE: str = "complete"
    ERROR: str = "error"


ANALYSIS_SCHEMA_VERSION = 1
