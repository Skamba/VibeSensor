"""Pure connection-loop planning for Bluetooth OBD runtime control."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vibesensor.domain import SpeedSourceKind

__all__ = [
    "ObdConnectionLoopSnapshot",
    "ObdConnectionStep",
    "ObdConnectionStepKind",
    "plan_connection_step",
]


class ObdConnectionStepKind(StrEnum):
    IDLE = "idle"
    MISSING_CONFIG = "missing_config"
    REPLACE_SESSION = "replace_session"
    CONNECT = "connect"
    WAIT = "wait"
    POLL = "poll"


@dataclass(frozen=True, slots=True)
class ObdConnectionLoopSnapshot:
    selected_source: SpeedSourceKind
    configured_mac: str | None
    configured_name: str | None
    has_session: bool
    session_device_mac: str | None
    poll_wait_s: float | None = None


@dataclass(frozen=True, slots=True)
class ObdConnectionStep:
    kind: ObdConnectionStepKind
    sleep_s: float = 0.0
    error: str | None = None
    mac_address: str | None = None
    configured_name: str | None = None
    close_session: bool = False


def plan_connection_step(
    snapshot: ObdConnectionLoopSnapshot,
    *,
    idle_poll_s: float,
) -> ObdConnectionStep:
    """Interpret the observed loop state into one side-effectful control step."""

    if snapshot.selected_source is not SpeedSourceKind.OBD2:
        return ObdConnectionStep(
            kind=ObdConnectionStepKind.IDLE,
            sleep_s=idle_poll_s,
            close_session=snapshot.has_session,
        )
    if snapshot.configured_mac is None:
        return ObdConnectionStep(
            kind=ObdConnectionStepKind.MISSING_CONFIG,
            sleep_s=idle_poll_s,
            error="No configured Bluetooth OBD adapter",
            close_session=snapshot.has_session,
        )
    if snapshot.has_session and snapshot.session_device_mac != snapshot.configured_mac:
        return ObdConnectionStep(
            kind=ObdConnectionStepKind.REPLACE_SESSION,
            close_session=True,
        )
    if not snapshot.has_session:
        return ObdConnectionStep(
            kind=ObdConnectionStepKind.CONNECT,
            mac_address=snapshot.configured_mac,
            configured_name=snapshot.configured_name,
        )
    if snapshot.poll_wait_s is not None and snapshot.poll_wait_s > 0:
        return ObdConnectionStep(
            kind=ObdConnectionStepKind.WAIT,
            sleep_s=snapshot.poll_wait_s,
        )
    return ObdConnectionStep(kind=ObdConnectionStepKind.POLL)
