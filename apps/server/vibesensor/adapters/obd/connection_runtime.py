"""Connection-loop execution for Bluetooth OBD monitoring."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.connection_executor import (
    ObdConnectionExecutor,
    ObdConnectionLoopState,
)
from vibesensor.adapters.obd.connection_plan import (
    ObdConnectionLoopSnapshot,
    ObdConnectionStep,
    plan_connection_step,
)
from vibesensor.adapters.obd.elm327 import Elm327Session
from vibesensor.adapters.obd.runtime_connection_state import ObdRuntimeConnectionState

__all__ = ["ObdConnectionRuntime"]

_IDLE_POLL_S = 1.0

SessionFactory = Callable[[], Elm327Session]
MonotonicFn = Callable[[], float]


class ObdConnectionRuntime:
    """Own session lifecycle, reconnect behavior, and blocking poll execution."""

    __slots__ = (
        "_connection_state",
        "_executor",
    )

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient,
        connection_state: ObdRuntimeConnectionState,
        session_factory: SessionFactory,
        monotonic: MonotonicFn = time.monotonic,
    ) -> None:
        self._connection_state = connection_state
        self._executor = ObdConnectionExecutor(
            admin_client=admin_client,
            connection_state=connection_state,
            session_factory=session_factory,
            monotonic=monotonic,
        )

    async def run(self) -> None:
        state = ObdConnectionLoopState()
        try:
            while True:
                step = self._plan_loop_step(
                    session=state.session,
                    session_device_mac=state.session_device_mac,
                )
                state = await self._executor.execute(
                    state=state,
                    step=step,
                )
        except asyncio.CancelledError:
            await self._executor.close(state=state)
            raise

    def _plan_loop_step(
        self,
        *,
        session: Elm327Session | None,
        session_device_mac: str | None,
    ) -> ObdConnectionStep:
        (
            selected_source,
            configured_mac,
            configured_name,
        ) = self._connection_state.configured_device_snapshot()
        return plan_connection_step(
            ObdConnectionLoopSnapshot(
                selected_source=selected_source,
                configured_mac=configured_mac,
                configured_name=configured_name,
                has_session=session is not None,
                session_device_mac=session_device_mac,
                poll_wait_s=(self._connection_state.next_wait_s() if session is not None else None),
            ),
            idle_poll_s=_IDLE_POLL_S,
        )
