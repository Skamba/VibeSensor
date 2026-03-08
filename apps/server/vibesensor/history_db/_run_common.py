"""Shared run-history constants for HistoryDB."""

from __future__ import annotations

from typing import Final


class RunStatus:
    """String constants for the ``runs.status`` column."""

    RECORDING: str = "recording"
    ANALYZING: str = "analyzing"
    COMPLETE: str = "complete"
    ERROR: str = "error"


RUN_TRANSITIONS: Final[dict[str | None, frozenset[str]]] = {
    None: frozenset({RunStatus.RECORDING}),
    RunStatus.RECORDING: frozenset({RunStatus.ANALYZING, RunStatus.ERROR}),
    RunStatus.ANALYZING: frozenset({RunStatus.COMPLETE, RunStatus.ERROR}),
    RunStatus.COMPLETE: frozenset(),
    RunStatus.ERROR: frozenset(),
}


def can_transition_run(current_status: str | None, target_status: str) -> bool:
    """Return whether a run can legally move from ``current_status`` to ``target_status``."""
    return target_status in RUN_TRANSITIONS.get(current_status, frozenset())


ANALYSIS_SCHEMA_VERSION = 1
