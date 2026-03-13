"""Aggregate root for a vibration-diagnostic measurement session.

``Run`` tracks the lifecycle (start / stop) for one diagnostic run.
``DiagnosticSession`` is kept as a backward-compatibility alias.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "DiagnosticSession",
    "Run",
    "SessionStatus",
]


class SessionStatus(StrEnum):
    """Lifecycle states of a :class:`Run`."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass
class Run:
    """Aggregate root for a vibration-diagnostic measurement session.

    Tracks the lifecycle (start / stop) for one diagnostic run.

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
            If the session has already been started or stopped.
        """
        if self.status is not SessionStatus.PENDING:
            raise RuntimeError(
                f"Cannot start session in '{self.status.value}' state; "
                f"expected '{SessionStatus.PENDING.value}'."
            )
        self.status = SessionStatus.RUNNING

    def stop(self) -> None:
        """Transition the session to *stopped*.

        Raises
        ------
        RuntimeError
            If the session is not currently running.
        """
        if self.status is not SessionStatus.RUNNING:
            raise RuntimeError(
                f"Cannot stop session in '{self.status.value}' state; "
                f"expected '{SessionStatus.RUNNING.value}'."
            )
        self.status = SessionStatus.STOPPED

    # -- queries ------------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        """Whether the session has been stopped."""
        return self.status is SessionStatus.STOPPED


# Backward-compatibility alias
DiagnosticSession = Run
