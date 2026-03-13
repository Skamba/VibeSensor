"""Aggregate root for a vibration-diagnostic measurement session.

``Run`` tracks the in-memory lifecycle of a single diagnostic session.
``SessionStatus`` covers the in-memory states (PENDING → RUNNING).

The *persisted* run lifecycle is tracked by ``RunStatus`` in
``domain/run_status.py`` (RECORDING → ANALYZING → COMPLETE | ERROR).
Route handlers bridge the two: ``Run.start()`` coincides with creating
a DB row in RECORDING status, and discarding the ``Run`` object
coincides with transitioning the DB row to ANALYZING.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "Run",
    "SessionStatus",
]


class SessionStatus(StrEnum):
    """Lifecycle states of a :class:`Run` (in-memory session only)."""

    PENDING = "pending"
    RUNNING = "running"


@dataclass
class Run:
    """Aggregate root for a vibration-diagnostic measurement session.

    Tracks the in-memory lifecycle for one diagnostic run.  The ``Run``
    object is created with status PENDING, transitioned to RUNNING via
    :meth:`start`, and then discarded when the recording stops.  There
    is no ``stop()`` method — the route handler simply drops the
    reference.

    Parameters
    ----------
    session_id:
        Unique session identifier (UUID hex string).
    analysis_settings:
        Snapshot of analysis settings active at session start.
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    analysis_settings: dict[str, float] = field(default_factory=dict)

    status: SessionStatus = field(default=SessionStatus.PENDING, init=False)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Transition the session to *running*.

        Raises
        ------
        RuntimeError
            If the session has already been started.
        """
        if self.status is not SessionStatus.PENDING:
            raise RuntimeError(
                f"Cannot start session in '{self.status.value}' state; "
                f"expected '{SessionStatus.PENDING.value}'."
            )
        self.status = SessionStatus.RUNNING
