"""Connection-loop execution for Bluetooth OBD monitoring."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.connection_plan import (
    ObdConnectionLoopSnapshot,
    ObdConnectionStep,
    ObdConnectionStepKind,
    plan_connection_step,
)
from vibesensor.adapters.obd.elm327 import Elm327Session, ObdTransportError
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.polling import ObdPollResult, execute_poll_plan
from vibesensor.adapters.obd.runtime_controller import ObdRuntimeController
from vibesensor.shared.operational_errors import OperationalError, ServiceUnavailableError

__all__ = ["ObdConnectionRuntime"]

_INITIAL_RECONNECT_DELAY_S = 1.0
_MAX_RECONNECT_DELAY_S = 30.0
_IDLE_POLL_S = 1.0

SessionFactory = Callable[[], Elm327Session]
MonotonicFn = Callable[[], float]


class ObdConnectionRuntime:
    """Own session lifecycle, reconnect behavior, and blocking poll execution."""

    __slots__ = (
        "_admin_client",
        "_monotonic",
        "_runtime",
        "_session_factory",
    )

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient,
        runtime: ObdRuntimeController,
        session_factory: SessionFactory,
        monotonic: MonotonicFn = time.monotonic,
    ) -> None:
        self._admin_client = admin_client
        self._runtime = runtime
        self._session_factory = session_factory
        self._monotonic = monotonic

    async def run(self) -> None:
        session: Elm327Session | None = None
        session_device_mac: str | None = None
        reconnect_delay = _INITIAL_RECONNECT_DELAY_S
        try:
            while True:
                step = self._plan_loop_step(
                    session=session,
                    session_device_mac=session_device_mac,
                )
                session, session_device_mac = await self._close_session_if_needed(
                    session=session,
                    session_device_mac=session_device_mac,
                    close_session=step.close_session,
                )
                if step.kind is ObdConnectionStepKind.IDLE:
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    await asyncio.sleep(step.sleep_s)
                    continue
                if step.kind is ObdConnectionStepKind.MISSING_CONFIG:
                    self._runtime.mark_disconnected(
                        error=step.error,
                    )
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    await asyncio.sleep(step.sleep_s)
                    continue
                if step.kind is ObdConnectionStepKind.REPLACE_SESSION:
                    continue
                if step.kind is ObdConnectionStepKind.CONNECT:
                    assert step.mac_address is not None
                    self._runtime.mark_connecting()
                    try:
                        session, device = await asyncio.to_thread(
                            self._connect_blocking,
                            step.mac_address,
                            step.configured_name,
                        )
                    except (OperationalError, OSError, ObdTransportError) as exc:
                        self._runtime.mark_disconnected(
                            error=str(exc),
                            reconnect_delay_s=reconnect_delay,
                        )
                        await asyncio.sleep(reconnect_delay)
                        reconnect_delay = min(reconnect_delay * 2.0, _MAX_RECONNECT_DELAY_S)
                        continue
                    session_device_mac = device.mac_address
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    self._runtime.mark_connected(device)
                    continue
                if step.kind is ObdConnectionStepKind.WAIT:
                    await asyncio.sleep(step.sleep_s)
                    continue
                assert session is not None
                poll_result = await asyncio.to_thread(self._poll_cycle_blocking, session)
                connection_lost = self._runtime.apply_poll_cycle(
                    poll_result,
                    reconnect_delay_s=reconnect_delay,
                )
                if connection_lost:
                    await asyncio.to_thread(session.close)
                    session = None
                    session_device_mac = None
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2.0, _MAX_RECONNECT_DELAY_S)
        except asyncio.CancelledError:
            if session is not None:
                await asyncio.to_thread(session.close)
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
        ) = self._runtime.configured_device_snapshot()
        return plan_connection_step(
            ObdConnectionLoopSnapshot(
                selected_source=selected_source,
                configured_mac=configured_mac,
                configured_name=configured_name,
                has_session=session is not None,
                session_device_mac=session_device_mac,
                poll_wait_s=self._runtime.next_wait_s() if session is not None else None,
            ),
            idle_poll_s=_IDLE_POLL_S,
        )

    def _connect_blocking(
        self,
        mac_address: str,
        configured_name: str | None,
    ) -> tuple[Elm327Session, ObdDeviceSnapshot]:
        info = self._admin_client.device_info(mac_address)
        if not info.paired:
            raise ServiceUnavailableError("Configured OBD adapter is not paired")
        if not info.trusted:
            raise ServiceUnavailableError("Configured OBD adapter is not trusted")
        if info.rfcomm_channel is None:
            raise ServiceUnavailableError("Bluetooth OBD adapter exposes no RFCOMM serial channel")
        session = self._session_factory()
        session.connect(mac_address, info.rfcomm_channel)
        self._initialize_session(session)
        device = replace(
            info,
            name=info.name or configured_name,
            connected=True,
        )
        return session, device

    def _initialize_session(self, session: Elm327Session) -> None:
        initialized = False
        try:
            session.initialize()
            initialized = True
        finally:
            if not initialized:
                session.close()

    def _poll_cycle_blocking(self, session: Elm327Session) -> ObdPollResult:
        plan = self._runtime.prepare_poll()
        return execute_poll_plan(session, plan=plan, monotonic=self._monotonic)

    async def _close_session_if_needed(
        self,
        *,
        session: Elm327Session | None,
        session_device_mac: str | None,
        close_session: bool,
    ) -> tuple[Elm327Session | None, str | None]:
        if close_session and session is not None:
            await asyncio.to_thread(session.close)
            return None, None
        return session, session_device_mac
