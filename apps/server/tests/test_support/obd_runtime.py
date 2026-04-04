from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from unittest.mock import MagicMock

from vibesensor.adapters.obd.admin_runtime import ObdAdminRuntime
from vibesensor.adapters.obd.connection_executor import ObdConnectionExecutor
from vibesensor.adapters.obd.connection_runtime import ObdConnectionRuntime
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.runtime_connection_state import ObdRuntimeConnectionState
from vibesensor.adapters.obd.runtime_observation import ObdRuntimeObservation
from vibesensor.adapters.obd.runtime_settings import ObdRuntimeSettings
from vibesensor.adapters.obd.runtime_store import ObdRuntimeStore


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass(slots=True)
class ObdRuntimeParts:
    store: ObdRuntimeStore
    observation: ObdRuntimeObservation
    settings: ObdRuntimeSettings
    connection_state: ObdRuntimeConnectionState
    admin: ObdAdminRuntime
    executor: ObdConnectionExecutor
    runner: ObdConnectionRuntime
    session: MagicMock
    admin_client: MagicMock


def build_obd_runtime_parts(
    *,
    clock: Callable[[], float],
    admin_client: MagicMock | None = None,
    session: MagicMock | None = None,
    sleep: Callable[[float], Awaitable[object]] | None = None,
) -> ObdRuntimeParts:
    admin = MagicMock() if admin_client is None else admin_client
    if admin_client is None:
        admin.device_info.return_value = ObdDeviceSnapshot(
            mac_address="00043e5a4a4d",
            name="OBDLink MX+",
            paired=True,
            trusted=True,
            connected=False,
            rfcomm_channel=1,
        )
    resolved_session = MagicMock() if session is None else session
    store = ObdRuntimeStore(
        monotonic=clock,
        poll_interval_s=0.75,
        initial_reconnect_delay_s=1.0,
        engine_rpm_stale_timeout_s=2.0,
    )
    connection_state = ObdRuntimeConnectionState(store=store)
    executor = ObdConnectionExecutor(
        admin_client=admin,
        connection_state=connection_state,
        session_factory=lambda: resolved_session,
        monotonic=clock,
        **({} if sleep is None else {"sleep": sleep}),
    )
    runner = ObdConnectionRuntime(
        admin_client=admin,
        connection_state=connection_state,
        session_factory=lambda: resolved_session,
        monotonic=clock,
    )
    return ObdRuntimeParts(
        store=store,
        observation=ObdRuntimeObservation(store=store),
        settings=ObdRuntimeSettings(store=store),
        connection_state=connection_state,
        admin=ObdAdminRuntime(
            admin_client=admin,
            connection_state=connection_state,
        ),
        executor=executor,
        runner=runner,
        session=resolved_session,
        admin_client=admin,
    )


def build_connected_obd_runtime_parts(
    *,
    clock: Callable[[], float],
    admin_client: MagicMock | None = None,
    session: MagicMock | None = None,
    sleep: Callable[[float], Awaitable[object]] | None = None,
) -> ObdRuntimeParts:
    parts = build_obd_runtime_parts(
        clock=clock,
        admin_client=admin_client,
        session=session,
        sleep=sleep,
    )
    parts.settings.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        stale_timeout_s=5.0,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )
    _, device = parts.executor._connect_blocking("00043e5a4a4d", "OBDLink MX+")
    parts.connection_state.mark_connected(device)
    return parts
