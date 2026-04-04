"""Focused Bluetooth OBD runtime role builders over shared runtime state."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.admin_runtime import ObdAdminRuntime
from vibesensor.adapters.obd.connection_runtime import ObdConnectionRuntime
from vibesensor.adapters.obd.elm327 import Elm327Session
from vibesensor.adapters.obd.runtime_connection_control import ObdRuntimeConnectionControl
from vibesensor.adapters.obd.runtime_connection_observation import (
    ObdRuntimeConnectionObservation,
)
from vibesensor.adapters.obd.runtime_facts import ObdRuntimeFacts
from vibesensor.adapters.obd.runtime_projection import ObdRuntimeProjection
from vibesensor.adapters.obd.runtime_settings import ObdRuntimeSettings
from vibesensor.adapters.obd.runtime_store import MonotonicFn, ObdRuntimeStore

__all__ = [
    "ObdRuntime",
    "ObdRuntimeConnection",
    "ObdRuntimeControl",
    "ObdRuntimeObservation",
    "build_obd_runtime",
]

_DEFAULT_POLL_INTERVAL_S = 0.75
_RPM_STALE_TIMEOUT_S = 2.0
_INITIAL_RECONNECT_DELAY_S = 1.0

SessionFactory = Callable[[], Elm327Session]


@dataclass(frozen=True, slots=True)
class ObdRuntimeObservation:
    """Read-only OBD observation surface."""

    facts: ObdRuntimeFacts
    projection: ObdRuntimeProjection


@dataclass(frozen=True, slots=True)
class ObdRuntimeControl:
    """Configuration and admin-control surface."""

    settings: ObdRuntimeSettings
    admin: ObdAdminRuntime


@dataclass(frozen=True, slots=True)
class ObdRuntimeConnection:
    """Connection execution surface."""

    runner: ObdConnectionRuntime


@dataclass(frozen=True, slots=True)
class ObdRuntime:
    """Role-grouped OBD runtime surfaces for callers."""

    observation: ObdRuntimeObservation
    control: ObdRuntimeControl
    connection: ObdRuntimeConnection


def build_obd_runtime(
    *,
    admin_client: ObdAdminClient | None = None,
    session_factory: SessionFactory | None = None,
    monotonic: MonotonicFn = time.monotonic,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
) -> ObdRuntime:
    """Build role-grouped OBD runtime surfaces over one shared runtime store."""

    resolved_admin_client = ObdAdminClient() if admin_client is None else admin_client
    resolved_session_factory = Elm327Session if session_factory is None else session_factory
    store = ObdRuntimeStore(
        monotonic=monotonic,
        poll_interval_s=poll_interval_s,
        initial_reconnect_delay_s=_INITIAL_RECONNECT_DELAY_S,
        engine_rpm_stale_timeout_s=_RPM_STALE_TIMEOUT_S,
    )
    connection_control = ObdRuntimeConnectionControl(store=store)
    connection_observation = ObdRuntimeConnectionObservation(store=store)
    return ObdRuntime(
        observation=ObdRuntimeObservation(
            facts=ObdRuntimeFacts(store=store),
            projection=ObdRuntimeProjection(store=store),
        ),
        control=ObdRuntimeControl(
            settings=ObdRuntimeSettings(store=store),
            admin=ObdAdminRuntime(
                admin_client=resolved_admin_client,
                store=store,
            ),
        ),
        connection=ObdRuntimeConnection(
            runner=ObdConnectionRuntime(
                admin_client=resolved_admin_client,
                connection_observation=connection_observation,
                connection_control=connection_control,
                session_factory=resolved_session_factory,
                monotonic=monotonic,
            ),
        ),
    )
