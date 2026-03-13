"""Aggregate root for a vibration-diagnostic measurement run.

``Run`` tracks the in-memory lifecycle of a single diagnostic run.
``RunPhase`` covers the in-memory states (PENDING → RUNNING → STOPPED).

The *persisted* run lifecycle is tracked by ``RunStatus`` in
``domain/run_status.py`` (RECORDING → ANALYZING → COMPLETE | ERROR).
Route handlers bridge the two: ``Run.start()`` coincides with creating
a DB row in RECORDING status, and ``Run.stop()`` coincides with
transitioning the DB row to ANALYZING.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "Run",
    "RunPhase",
]


class RunPhase(StrEnum):
    """Lifecycle states of a :class:`Run` (in-memory session only)."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass
class Run:
    """Aggregate root for a vibration-diagnostic measurement run.

    Tracks the in-memory lifecycle for one diagnostic run.  The ``Run``
    object is created in PENDING phase, transitioned to RUNNING via
    :meth:`start`, and then to STOPPED via :meth:`stop`.

    Parameters
    ----------
    run_id:
        Unique run identifier (UUID hex string).
    analysis_settings:
        Snapshot of analysis settings active at run start.
    """

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    analysis_settings: dict[str, float] = field(default_factory=dict)

    phase: RunPhase = field(default=RunPhase.PENDING, init=False)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Transition the run to *running*.

        Raises
        ------
        RuntimeError
            If the run has already been started.
        """
        if self.phase is not RunPhase.PENDING:
            raise RuntimeError(
                f"Cannot start run in '{self.phase.value}' phase; "
                f"expected '{RunPhase.PENDING.value}'."
            )
        self.phase = RunPhase.RUNNING

    def stop(self) -> None:
        """Transition the run to *stopped*.

        Raises
        ------
        RuntimeError
            If the run is not currently running.
        """
        if self.phase is not RunPhase.RUNNING:
            raise RuntimeError(
                f"Cannot stop run in '{self.phase.value}' phase; "
                f"expected '{RunPhase.RUNNING.value}'."
            )
        self.phase = RunPhase.STOPPED
