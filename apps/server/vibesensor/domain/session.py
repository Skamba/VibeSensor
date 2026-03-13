"""Aggregate root for a vibration-diagnostic measurement session.

``DiagnosticSession`` (primary name: ``Run``) tracks the lifecycle
(start / stop) and accumulated readings for one diagnostic run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .measurement import AccelerationSample, VibrationReading

__all__ = [
    "DiagnosticSession",
    "Run",
    "SessionStatus",
]


class SessionStatus(StrEnum):
    """Lifecycle states of a :class:`DiagnosticSession`."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass
class DiagnosticSession:
    """Aggregate root for a vibration-diagnostic measurement session.

    Tracks the lifecycle (start / stop) and accumulated readings for one
    diagnostic run.  State fields are modelled after ``run_context.py``
    and ``runlog.py`` metadata.

    Parameters
    ----------
    session_id:
        Unique session identifier (UUID hex string).
    vehicle_id:
        Optional identifier for the vehicle under test.
    analysis_settings:
        Snapshot of analysis settings active at session start.
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    vehicle_id: str | None = None
    analysis_settings: dict[str, float] = field(default_factory=dict)

    status: SessionStatus = field(default=SessionStatus.PENDING, init=False)
    start_time: datetime | None = field(default=None, init=False)
    stop_time: datetime | None = field(default=None, init=False)
    _readings: list[VibrationReading] = field(default_factory=list, init=False, repr=False)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Transition the session to *running* and record the start time.

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
        self.start_time = datetime.now(UTC)

    def stop(self) -> None:
        """Transition the session to *stopped* and record the stop time.

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
        self.stop_time = datetime.now(UTC)

    # -- sample processing --------------------------------------------------

    def process_sample(
        self,
        sample: AccelerationSample,
        noise_floor: float,
    ) -> VibrationReading:
        """Convert *sample* to a :class:`VibrationReading` and record it.

        Parameters
        ----------
        sample:
            Raw acceleration sample to process.
        noise_floor:
            Estimated noise-floor amplitude in *g*.

        Returns
        -------
        VibrationReading
            The resulting reading (also appended to the session's internal
            list).

        Raises
        ------
        RuntimeError
            If the session is not in the *running* state.
        """
        if self.status is not SessionStatus.RUNNING:
            raise RuntimeError(
                f"Cannot process samples in '{self.status.value}' state; "
                f"session must be '{SessionStatus.RUNNING.value}'."
            )
        reading = sample.to_vibration_reading(noise_floor)
        self._readings.append(reading)
        return reading

    # -- queries ------------------------------------------------------------

    @property
    def readings(self) -> list[VibrationReading]:
        """Return a shallow copy of all recorded readings."""
        return list(self._readings)

    @property
    def reading_count(self) -> int:
        """Return the number of recorded readings."""
        return len(self._readings)

    @property
    def has_readings(self) -> bool:
        """Whether any readings have been recorded."""
        return bool(self._readings)

    @property
    def duration(self) -> timedelta | None:
        """Elapsed time between start and stop, or ``None`` if incomplete."""
        if self.start_time is not None and self.stop_time is not None:
            return self.stop_time - self.start_time
        return None

    @property
    def duration_s(self) -> float | None:
        """Duration in seconds, or ``None`` if incomplete."""
        d = self.duration
        return d.total_seconds() if d is not None else None

    @property
    def is_complete(self) -> bool:
        """Whether the session has been stopped."""
        return self.status is SessionStatus.STOPPED

    def get_peak_vibration(self) -> VibrationReading | None:
        """Return the reading with the highest ``intensity_db``, or ``None``.

        Returns
        -------
        VibrationReading | None
            The peak reading, or ``None`` if no readings have been recorded.
        """
        if not self._readings:
            return None
        return max(self._readings, key=lambda r: r.intensity_db)


# Primary domain alias
Run = DiagnosticSession
