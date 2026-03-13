"""Aggregate root for a vibration-diagnostic measurement run.

``Run`` tracks the in-memory lifecycle of a single diagnostic run
through start/stop guards.  The *persisted* run lifecycle is tracked by
``RunStatus`` in ``domain/run_status.py`` (RECORDING → ANALYZING →
COMPLETE | ERROR).  Route handlers bridge the two: ``Run.start()``
coincides with creating a DB row in RECORDING status, and ``Run.stop()``
coincides with transitioning the DB row to ANALYZING.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

__all__ = [
    "Run",
]


@dataclass
class Run:
    """Aggregate root for a vibration-diagnostic measurement run.

    Tracks the in-memory lifecycle for one diagnostic run.  A ``Run``
    is created, started via :meth:`start`, then ended via :meth:`stop`.
    Use the :attr:`is_recording` property to query active state.

    Parameters
    ----------
    run_id:
        Unique run identifier (UUID hex string).
    analysis_settings:
        Snapshot of analysis settings active at run start.
    """

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    analysis_settings: dict[str, float] = field(default_factory=dict)

    _started: bool = field(default=False, init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)

    # -- queries ------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """``True`` while the run is actively recording (started, not stopped)."""
        return self._started and not self._stopped

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Mark the run as actively recording.

        Raises
        ------
        RuntimeError
            If the run has already been started.
        """
        if self._started:
            raise RuntimeError("Cannot start run: already started.")
        self._started = True

    def stop(self) -> None:
        """Mark the run as stopped (no longer recording).

        Raises
        ------
        RuntimeError
            If the run has not been started or has already been stopped.
        """
        if not self._started:
            raise RuntimeError("Cannot stop run: not yet started.")
        if self._stopped:
            raise RuntimeError("Cannot stop run: already stopped.")
        self._stopped = True
