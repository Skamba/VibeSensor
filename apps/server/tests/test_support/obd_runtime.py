from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from unittest.mock import MagicMock

from vibesensor.speed.obd.connection_executor import ObdConnectionExecutor
from vibesensor.speed.obd.models import ObdDeviceSnapshot
from vibesensor.speed.obd.service import ObdService


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass(slots=True)
class ObdRuntimeParts:
    obd: ObdService
    executor: ObdConnectionExecutor
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
    obd = ObdService(
        admin_client=admin,
        session_factory=lambda: resolved_session,
        monotonic=clock,
        poll_interval_s=0.75,
    )
    executor = ObdConnectionExecutor(
        admin_client=admin,
        obd=obd,
        session_factory=lambda: resolved_session,
        monotonic=clock,
        **({} if sleep is None else {"sleep": sleep}),
    )
    return ObdRuntimeParts(
        obd=obd,
        executor=executor,
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
    parts.obd.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        stale_timeout_s=5.0,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )
    configured_device = replace(
        parts.admin_client.device_info.return_value,
        name=parts.admin_client.device_info.return_value.name or "OBDLink MX+",
        connected=True,
    )
    parts.obd.mark_connected(configured_device)
    return parts
