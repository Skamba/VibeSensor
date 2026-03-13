"""Run-status lifecycle as a domain concept.

``RunStatus`` is a ``StrEnum`` so its members compare equal to plain
strings (``RunStatus.COMPLETE == "complete"``), preserving backward
compatibility with SQLite storage and existing dict-based code paths.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "RunStatus",
    "RUN_TRANSITIONS",
    "can_transition_run",
]


class RunStatus(StrEnum):
    """Lifecycle status of a persisted diagnostic run."""

    RECORDING = "recording"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    ERROR = "error"


RUN_TRANSITIONS: Final[dict[RunStatus | None, frozenset[RunStatus]]] = {
    None: frozenset({RunStatus.RECORDING}),
    RunStatus.RECORDING: frozenset({RunStatus.ANALYZING, RunStatus.COMPLETE, RunStatus.ERROR}),
    RunStatus.ANALYZING: frozenset({RunStatus.COMPLETE, RunStatus.ERROR}),
    RunStatus.COMPLETE: frozenset(),
    RunStatus.ERROR: frozenset(),
}


def can_transition_run(
    current_status: RunStatus | str | None,
    target_status: RunStatus | str,
) -> bool:
    """Return whether a run can legally move from *current_status* to *target_status*."""
    return target_status in RUN_TRANSITIONS.get(current_status, frozenset())  # type: ignore[arg-type]
