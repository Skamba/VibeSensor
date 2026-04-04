"""Typed transport-step failures emitted below the transport session boundary."""

from __future__ import annotations

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import UpdatePhase

__all__ = ["UpdateTransportStepError"]


class UpdateTransportStepError(UpdateTransportError):
    """Transport-step failure carrying the issue details for session-level handling."""

    __slots__ = ("detail", "phase")

    def __init__(
        self,
        *,
        phase: UpdatePhase | str,
        message: str,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.phase = phase.value if isinstance(phase, UpdatePhase) else phase
        self.detail = detail
