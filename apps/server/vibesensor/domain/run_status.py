"""Run-status lifecycle as a domain concept.

``RunStatus`` is a ``StrEnum`` so its members compare equal to plain
strings (``RunStatus.COMPLETE == "complete"``), enabling direct use as
SQLite column values and in dict-based code paths.

This tracks the *persisted* run lifecycle in the database.  The
in-memory run lifecycle is tracked by ``Run`` in ``domain/run.py``
(with ``start()``/``stop()`` guards and an ``is_recording`` property).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "RunStatus",
    "RUN_TRANSITIONS",
    "is_run_deletable",
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


_TERMINAL: Final[frozenset[RunStatus]] = frozenset({RunStatus.COMPLETE, RunStatus.ERROR})


def is_run_deletable(status: RunStatus | str) -> bool:
    """Return ``True`` if a run in *status* may be deleted.

    Only terminal states (``complete``, ``error``) are deletable.
    """
    return RunStatus(status) in _TERMINAL


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
