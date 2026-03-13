"""Run-status lifecycle as a domain concept.

``RunStatus`` is a ``StrEnum`` so its members compare equal to plain
strings (``RunStatus.COMPLETE == "complete"``), preserving backward
compatibility with SQLite storage and existing dict-based code paths.

This tracks the *persisted* run lifecycle in the database.  The
in-memory run lifecycle is tracked by ``Run`` in ``domain/session.py``
(with ``start()``/``stop()`` guards and an ``is_recording`` property).
Route handlers bridge the two models; see ``session.py`` module
docstring for details.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "RunStatus",
    "RUN_TRANSITIONS",
    "transition_run",
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


def transition_run(
    current_status: RunStatus | str | None,
    target_status: RunStatus | str,
) -> RunStatus:
    """Validate and return *target_status* if the transition is legal.

    Raises
    ------
    ValueError
        If *current_status* → *target_status* is not a valid transition
        according to :data:`RUN_TRANSITIONS`.
    """
    if target_status in RUN_TRANSITIONS.get(current_status, frozenset()):  # type: ignore[arg-type]
        return RunStatus(target_status)
    raise ValueError(f"Invalid run transition: {current_status!r} → {target_status!r}")
