"""Pure runtime-control decisions for Bluetooth OBD policy changes."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.adapters.obd.runtime_policy import ObdPolicyUpdate
from vibesensor.adapters.obd.runtime_state import ObdRuntimeState

__all__ = [
    "ObdRuntimeControlDecision",
    "apply_runtime_control_decision",
    "resolve_runtime_control_decision",
]


@dataclass(frozen=True, slots=True)
class ObdRuntimeControlDecision:
    connection_state: str
    reset_observed_device_state: bool = True
    clear_runtime_error: bool = True


def resolve_runtime_control_decision(
    update: ObdPolicyUpdate,
) -> ObdRuntimeControlDecision | None:
    """Separate policy meaning from runtime-side control actions."""

    if not update.obd_selected:
        return ObdRuntimeControlDecision(connection_state="idle")
    if update.configured_device_missing or update.configured_device_changed:
        return ObdRuntimeControlDecision(connection_state="disconnected")
    return None


def apply_runtime_control_decision(
    runtime_state: ObdRuntimeState,
    decision: ObdRuntimeControlDecision | None,
) -> None:
    if decision is None:
        return
    if decision.reset_observed_device_state:
        runtime_state.reset_observed_device_state(
            clear_runtime_error=decision.clear_runtime_error,
        )
    runtime_state.set_connection_state(decision.connection_state, error=None)
