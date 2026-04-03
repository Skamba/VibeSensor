"""Explicit phase-transition policy for update job status."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import UpdatePhase

_ALLOWED_PHASE_TRANSITIONS: dict[UpdatePhase, frozenset[UpdatePhase]] = {
    UpdatePhase.idle: frozenset(),
    UpdatePhase.validating: frozenset(
        {
            UpdatePhase.stopping_hotspot,
            UpdatePhase.connecting_usb_internet,
        },
    ),
    UpdatePhase.stopping_hotspot: frozenset(
        {
            UpdatePhase.connecting_wifi,
            UpdatePhase.restoring_hotspot,
        },
    ),
    UpdatePhase.connecting_wifi: frozenset(
        {
            UpdatePhase.checking,
            UpdatePhase.restoring_hotspot,
        },
    ),
    UpdatePhase.connecting_usb_internet: frozenset({UpdatePhase.checking}),
    UpdatePhase.checking: frozenset(
        {
            UpdatePhase.downloading,
            UpdatePhase.restoring_hotspot,
            UpdatePhase.done,
        },
    ),
    UpdatePhase.downloading: frozenset(
        {
            UpdatePhase.installing,
            UpdatePhase.restoring_hotspot,
        },
    ),
    UpdatePhase.installing: frozenset(
        {
            UpdatePhase.restoring_hotspot,
            UpdatePhase.done,
        },
    ),
    UpdatePhase.restoring_hotspot: frozenset({UpdatePhase.done}),
    UpdatePhase.done: frozenset(),
}

_SUCCESS_COMPLETION_PHASES = frozenset(
    {
        UpdatePhase.checking,
        UpdatePhase.installing,
        UpdatePhase.restoring_hotspot,
    },
)


class UpdatePhaseTransitionError(ValueError):
    """Raised when the update workflow attempts an invalid phase transition."""


class UpdatePhaseStateMachine:
    """Validate the canonical in-progress phase graph for update jobs."""

    __slots__ = ()

    def ensure_transition(self, current: UpdatePhase, target: UpdatePhase) -> None:
        if target == current:
            return
        allowed = _ALLOWED_PHASE_TRANSITIONS[current]
        if target in allowed:
            return
        raise UpdatePhaseTransitionError(
            f"Invalid update phase transition: {current.value} -> {target.value}",
        )

    def ensure_success_completion(self, current: UpdatePhase) -> None:
        if current in _SUCCESS_COMPLETION_PHASES:
            return
        raise UpdatePhaseTransitionError(
            f"Cannot mark update success from phase {current.value}",
        )
