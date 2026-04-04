"""Bluetooth OBD live-speed facade over runtime, admin, and connection collaborators."""

from __future__ import annotations

import time
from collections.abc import Callable

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.admin_runtime import ObdAdminRuntime
from vibesensor.adapters.obd.connection_runtime import ObdConnectionRuntime
from vibesensor.adapters.obd.elm327 import Elm327Session
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.adapters.obd.runtime_controller import ObdRuntimeController
from vibesensor.domain import SpeedSourceKind

__all__ = ["OBDSpeedMonitor"]

_DEFAULT_POLL_INTERVAL_S = 0.75
_RPM_STALE_TIMEOUT_S = 2.0
_INITIAL_RECONNECT_DELAY_S = 1.0


SessionFactory = Callable[[], Elm327Session]
MonotonicFn = Callable[[], float]


class OBDSpeedMonitor:
    """Public OBD monitor facade over state control, admin observation, and connection loop."""

    __slots__ = ("_admin", "_connection_runtime", "_runtime")

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient | None = None,
        session_factory: SessionFactory | None = None,
        monotonic: MonotonicFn = time.monotonic,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        resolved_admin_client = ObdAdminClient() if admin_client is None else admin_client
        resolved_session_factory = Elm327Session if session_factory is None else session_factory
        self._runtime = ObdRuntimeController(
            monotonic=monotonic,
            poll_interval_s=poll_interval_s,
            initial_reconnect_delay_s=_INITIAL_RECONNECT_DELAY_S,
            engine_rpm_stale_timeout_s=_RPM_STALE_TIMEOUT_S,
        )
        self._admin = ObdAdminRuntime(
            admin_client=resolved_admin_client,
            runtime=self._runtime,
        )
        self._connection_runtime = ObdConnectionRuntime(
            admin_client=resolved_admin_client,
            runtime=self._runtime,
            session_factory=resolved_session_factory,
            monotonic=monotonic,
        )

    @property
    def speed_mps(self) -> float | None:
        return self._runtime.speed_mps

    @property
    def stale_timeout_s(self) -> float:
        return self._runtime.stale_timeout_s

    @property
    def engine_rpm(self) -> float | None:
        return self._runtime.engine_rpm

    @property
    def engine_rpm_source(self) -> str | None:
        return self._runtime.engine_rpm_source

    def resolve_speed(self) -> SpeedResolution:
        return self._runtime.resolve_speed()

    def apply_speed_source_settings(
        self,
        *,
        effective_speed_kmh: float | None,
        manual_source_selected: bool,
        stale_timeout_s: float | None = None,
        selected_source: SpeedSourceKind | str | None = None,
        obd_device_mac: str | None = None,
        obd_device_name: str | None = None,
    ) -> float | None:
        return self._runtime.apply_speed_source_settings(
            effective_speed_kmh=effective_speed_kmh,
            manual_source_selected=manual_source_selected,
            stale_timeout_s=stale_timeout_s,
            selected_source=selected_source,
            obd_device_mac=obd_device_mac,
            obd_device_name=obd_device_name,
        )

    def scan_devices(self, *, timeout_s: int = 8) -> list[ObdDeviceSnapshot]:
        return self._admin.scan_devices(timeout_s=timeout_s)

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        return self._admin.pair_device(mac_address)

    def set_manual_source_selected(self, selected: bool) -> None:
        self._runtime.set_manual_source_selected(selected)

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        return self._runtime.set_speed_override_kmh(speed_kmh)

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None:
        self._runtime.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)

    def refresh_admin_state(self) -> None:
        self._admin.refresh_configured_device()

    def status_snapshot(self) -> ObdStatusSnapshot:
        return self._runtime.status_snapshot()

    async def run(self) -> None:
        await self._connection_runtime.run()
