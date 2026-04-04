"""Focused Bluetooth OBD runtime services over shared runtime state."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.admin_runtime import ObdAdminRuntime
from vibesensor.adapters.obd.connection_runtime import ObdConnectionRuntime
from vibesensor.adapters.obd.elm327 import Elm327Session
from vibesensor.adapters.obd.runtime_admin_state import ObdRuntimeAdminState
from vibesensor.adapters.obd.runtime_connection_control import ObdRuntimeConnectionControl
from vibesensor.adapters.obd.runtime_facts import ObdRuntimeFacts
from vibesensor.adapters.obd.runtime_projection import ObdRuntimeProjection
from vibesensor.adapters.obd.runtime_settings import ObdRuntimeSettings
from vibesensor.adapters.obd.runtime_store import MonotonicFn, ObdRuntimeStore

__all__ = ["ObdRuntimeServices", "build_obd_runtime"]

_DEFAULT_POLL_INTERVAL_S = 0.75
_RPM_STALE_TIMEOUT_S = 2.0
_INITIAL_RECONNECT_DELAY_S = 1.0

SessionFactory = Callable[[], Elm327Session]


@dataclass(frozen=True, slots=True)
class ObdRuntimeServices:
    """Focused OBD services exposed to the rest of the application."""

    facts: ObdRuntimeFacts
    projection: ObdRuntimeProjection
    control: ObdRuntimeSettings
    admin: ObdAdminRuntime
    connection_control: ObdRuntimeConnectionControl
    runner: ObdConnectionRuntime


def build_obd_runtime(
    *,
    admin_client: ObdAdminClient | None = None,
    session_factory: SessionFactory | None = None,
    monotonic: MonotonicFn = time.monotonic,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
) -> ObdRuntimeServices:
    """Build focused OBD services over one shared runtime store."""

    resolved_admin_client = ObdAdminClient() if admin_client is None else admin_client
    resolved_session_factory = Elm327Session if session_factory is None else session_factory
    store = ObdRuntimeStore(
        monotonic=monotonic,
        poll_interval_s=poll_interval_s,
        initial_reconnect_delay_s=_INITIAL_RECONNECT_DELAY_S,
        engine_rpm_stale_timeout_s=_RPM_STALE_TIMEOUT_S,
    )
    connection_control = ObdRuntimeConnectionControl(store=store)
    admin_state = ObdRuntimeAdminState(store=store)
    return ObdRuntimeServices(
        facts=ObdRuntimeFacts(store=store),
        projection=ObdRuntimeProjection(store=store),
        control=ObdRuntimeSettings(store=store),
        admin=ObdAdminRuntime(
            admin_client=resolved_admin_client,
            admin_state=admin_state,
        ),
        connection_control=connection_control,
        runner=ObdConnectionRuntime(
            admin_client=resolved_admin_client,
            connection_control=connection_control,
            session_factory=resolved_session_factory,
            monotonic=monotonic,
        ),
    )
