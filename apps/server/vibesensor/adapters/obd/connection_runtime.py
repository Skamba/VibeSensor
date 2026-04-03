"""Connection-loop execution for Bluetooth OBD monitoring."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.elm327 import Elm327Session
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.polling import ObdPollResult, execute_poll_plan
from vibesensor.adapters.obd.runtime_controller import ObdRuntimeController
from vibesensor.domain import SpeedSourceKind
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
                selected_source, configured_mac, configured_name = (
                    self._runtime.configured_device_snapshot()
                )
                if selected_source is not SpeedSourceKind.OBD2:
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    session, session_device_mac = await self._idle(session)
                    await asyncio.sleep(_IDLE_POLL_S)
                    continue
                if configured_mac is None:
                    self._runtime.set_connection_state(
                        "disconnected",
                        error="No configured Bluetooth OBD adapter",
                    )
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    session, session_device_mac = await self._idle(session)
                    await asyncio.sleep(_IDLE_POLL_S)
                    continue
                if session is not None and session_device_mac != configured_mac:
                    await asyncio.to_thread(session.close)
                    session = None
                    session_device_mac = None
                if session is None:
                    self._runtime.set_connection_state("connecting", error=None)
                    try:
                        session, device = await asyncio.to_thread(
                            self._connect_blocking,
                            configured_mac,
                            configured_name,
                        )
                    except (OperationalError, RuntimeError) as exc:
                        self._runtime.set_connection_state(
                            "disconnected",
                            error=str(exc),
                            reconnect_delay_s=reconnect_delay,
                        )
                        await asyncio.sleep(reconnect_delay)
                        reconnect_delay = min(reconnect_delay * 2.0, _MAX_RECONNECT_DELAY_S)
                        continue
                    session_device_mac = device.mac_address
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    self._runtime.apply_device_snapshot(device)
                    self._runtime.reset_poll_schedule()
                    self._runtime.set_connection_state("connected", error=None)
                wait_s = self._runtime.next_wait_s()
                if wait_s > 0:
                    await asyncio.sleep(wait_s)
                    continue
                assert session is not None
                poll_result = await asyncio.to_thread(self._poll_cycle_blocking, session)
                self._runtime.apply_poll_result(poll_result)
                if poll_result.connection_lost:
                    await asyncio.to_thread(session.close)
                    session = None
                    session_device_mac = None
                    self._runtime.set_connection_state(
                        "disconnected",
                        error=self._runtime.status_snapshot().last_error,
                        reconnect_delay_s=reconnect_delay,
                    )
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2.0, _MAX_RECONNECT_DELAY_S)
        except asyncio.CancelledError:
            if session is not None:
                await asyncio.to_thread(session.close)
            raise

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
        try:
            session.initialize()
        except (OSError, OperationalError, RuntimeError):
            session.close()
            raise
        device = replace(
            info,
            name=info.name or configured_name,
            connected=True,
        )
        return session, device

    def _poll_cycle_blocking(self, session: Elm327Session) -> ObdPollResult:
        plan = self._runtime.prepare_poll()
        return execute_poll_plan(session, plan=plan, monotonic=self._monotonic)

    async def _idle(
        self,
        session: Elm327Session | None,
    ) -> tuple[Elm327Session | None, str | None]:
        if session is not None:
            await asyncio.to_thread(session.close)
        return None, None
