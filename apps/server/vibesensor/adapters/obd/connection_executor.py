"""Step execution and fault boundaries for Bluetooth OBD connection control."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.connection_plan import ObdConnectionStep, ObdConnectionStepKind
from vibesensor.adapters.obd.elm327 import Elm327Session, ObdTransportError
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.polling import ObdPollResult, execute_poll_plan
from vibesensor.adapters.obd.runtime_connection_state import ObdRuntimeConnectionState
from vibesensor.shared.operational_errors import OperationalError, ServiceUnavailableError

__all__ = ["ObdConnectionExecutor", "ObdConnectionLoopState"]

_INITIAL_RECONNECT_DELAY_S = 1.0
_MAX_RECONNECT_DELAY_S = 30.0

SessionFactory = Callable[[], Elm327Session]
MonotonicFn = Callable[[], float]
SleepFn = Callable[[float], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class ObdConnectionLoopState:
    session: Elm327Session | None = None
    session_device_mac: str | None = None
    reconnect_delay_s: float = _INITIAL_RECONNECT_DELAY_S


class ObdConnectionExecutor:
    """Own step-specific connection behavior and its operational fault boundaries."""

    __slots__ = (
        "_admin_client",
        "_connection_state",
        "_monotonic",
        "_session_factory",
        "_sleep",
    )

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient,
        connection_state: ObdRuntimeConnectionState,
        session_factory: SessionFactory,
        monotonic: MonotonicFn = time.monotonic,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._admin_client = admin_client
        self._connection_state = connection_state
        self._session_factory = session_factory
        self._monotonic = monotonic
        self._sleep = sleep

    async def execute(
        self,
        *,
        state: ObdConnectionLoopState,
        step: ObdConnectionStep,
    ) -> ObdConnectionLoopState:
        resolved_state = await self._close_session_if_needed(
            state=state,
            close_session=step.close_session,
        )
        if step.kind is ObdConnectionStepKind.IDLE:
            return await self._run_idle_step(state=resolved_state, sleep_s=step.sleep_s)
        if step.kind is ObdConnectionStepKind.MISSING_CONFIG:
            return await self._run_missing_config_step(
                state=resolved_state,
                error=step.error,
                sleep_s=step.sleep_s,
            )
        if step.kind is ObdConnectionStepKind.REPLACE_SESSION:
            return resolved_state
        if step.kind is ObdConnectionStepKind.CONNECT:
            if step.mac_address is None:
                raise RuntimeError("CONNECT step requires a configured OBD adapter MAC address")
            return await self._run_connect_step(
                state=resolved_state,
                mac_address=step.mac_address,
                configured_name=step.configured_name,
            )
        if step.kind is ObdConnectionStepKind.WAIT:
            return await self._run_wait_step(state=resolved_state, sleep_s=step.sleep_s)
        if resolved_state.session is None:
            raise RuntimeError("POLL step requires an active OBD session")
        return await self._run_poll_step(state=resolved_state)

    async def close(self, *, state: ObdConnectionLoopState) -> ObdConnectionLoopState:
        return await self._close_session_if_needed(state=state, close_session=True)

    async def _run_idle_step(
        self,
        *,
        state: ObdConnectionLoopState,
        sleep_s: float,
    ) -> ObdConnectionLoopState:
        await self._sleep(sleep_s)
        return replace(state, reconnect_delay_s=_INITIAL_RECONNECT_DELAY_S)

    async def _run_missing_config_step(
        self,
        *,
        state: ObdConnectionLoopState,
        error: str | None,
        sleep_s: float,
    ) -> ObdConnectionLoopState:
        self._connection_state.mark_disconnected(error=error)
        await self._sleep(sleep_s)
        return replace(state, reconnect_delay_s=_INITIAL_RECONNECT_DELAY_S)

    async def _run_connect_step(
        self,
        *,
        state: ObdConnectionLoopState,
        mac_address: str,
        configured_name: str | None,
    ) -> ObdConnectionLoopState:
        self._connection_state.mark_connecting()
        try:
            session, device = await asyncio.to_thread(
                self._connect_blocking,
                mac_address,
                configured_name,
            )
        except (OperationalError, OSError, ObdTransportError) as exc:
            self._connection_state.mark_disconnected(
                error=str(exc),
                reconnect_delay_s=state.reconnect_delay_s,
            )
            await self._sleep(state.reconnect_delay_s)
            return replace(
                state,
                reconnect_delay_s=self._next_reconnect_delay(state.reconnect_delay_s),
            )
        self._connection_state.mark_connected(device)
        return ObdConnectionLoopState(
            session=session,
            session_device_mac=device.mac_address,
            reconnect_delay_s=_INITIAL_RECONNECT_DELAY_S,
        )

    async def _run_wait_step(
        self,
        *,
        state: ObdConnectionLoopState,
        sleep_s: float,
    ) -> ObdConnectionLoopState:
        await self._sleep(sleep_s)
        return state

    async def _run_poll_step(self, *, state: ObdConnectionLoopState) -> ObdConnectionLoopState:
        assert state.session is not None
        poll_result = await asyncio.to_thread(self._poll_cycle_blocking, state.session)
        connection_lost = self._connection_state.apply_poll_cycle(
            poll_result,
            reconnect_delay_s=state.reconnect_delay_s,
        )
        if not connection_lost:
            return state
        closed_state = await self._close_session_if_needed(state=state, close_session=True)
        await self._sleep(state.reconnect_delay_s)
        return replace(
            closed_state,
            reconnect_delay_s=self._next_reconnect_delay(state.reconnect_delay_s),
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
        plan = self._connection_state.prepare_poll()
        return execute_poll_plan(session, plan=plan, monotonic=self._monotonic)

    async def _close_session_if_needed(
        self,
        *,
        state: ObdConnectionLoopState,
        close_session: bool,
    ) -> ObdConnectionLoopState:
        if close_session and state.session is not None:
            await asyncio.to_thread(state.session.close)
            return replace(state, session=None, session_device_mac=None)
        return state

    @staticmethod
    def _next_reconnect_delay(reconnect_delay_s: float) -> float:
        return min(reconnect_delay_s * 2.0, _MAX_RECONNECT_DELAY_S)
