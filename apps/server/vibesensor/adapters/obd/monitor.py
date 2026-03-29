"""Bluetooth OBD live-speed runtime monitor."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from threading import RLock
from typing import NamedTuple

from vibesensor.adapters.gps.speed_resolution import SpeedResolution, SpeedResolutionPolicy
from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.elm327 import (
    Elm327Session,
    ObdTransportError,
    elm_response_has_no_data,
    parse_pid_010c_rpm,
    parse_pid_010d_speed_kmh,
)
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.domain import SpeedSourceKind
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import KMH_TO_MPS, MPS_TO_KMH

__all__ = ["OBDSpeedMonitor"]

_INITIAL_RECONNECT_DELAY_S = 1.0
_MAX_RECONNECT_DELAY_S = 30.0
_IDLE_POLL_S = 1.0
_DEFAULT_POLL_INTERVAL_S = 0.75


class _PollResult(NamedTuple):
    speed_mps: float | None
    speed_error: str | None
    rpm: float | None
    raw_response: str | None


SessionFactory = Callable[[], Elm327Session]
MonotonicFn = Callable[[], float]


class OBDSpeedMonitor:
    """Manage Bluetooth RFCOMM polling plus stale/fallback resolution for OBD speed."""

    __slots__ = (
        "_admin_client",
        "_configured_device_mac",
        "_configured_device_name",
        "_connection_state",
        "_current_reconnect_delay",
        "_device_connected",
        "_device_mac",
        "_device_name",
        "_engine_rpm",
        "_engine_rpm_ts",
        "_last_error",
        "_last_raw_response",
        "_lock",
        "_monotonic",
        "_paired",
        "_policy",
        "_poll_interval_s",
        "_rfcomm_channel",
        "_selected_source",
        "_session_factory",
        "_speed_snapshot",
        "_trusted",
    )

    def __init__(
        self,
        *,
        admin_client: ObdAdminClient | None = None,
        session_factory: SessionFactory | None = None,
        monotonic: MonotonicFn = time.monotonic,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._admin_client = ObdAdminClient() if admin_client is None else admin_client
        self._session_factory = Elm327Session if session_factory is None else session_factory
        self._monotonic = monotonic
        self._poll_interval_s = max(0.2, float(poll_interval_s))
        self._policy = SpeedResolutionPolicy(manual_source_selected=False)
        self._lock = RLock()
        self._selected_source = SpeedSourceKind.GPS
        self._configured_device_mac: str | None = None
        self._configured_device_name: str | None = None
        self._connection_state = "idle"
        self._device_mac: str | None = None
        self._device_name: str | None = None
        self._paired = False
        self._trusted = False
        self._device_connected = False
        self._rfcomm_channel: int | None = None
        self._speed_snapshot: tuple[float | None, float | None] = (None, None)
        self._engine_rpm: float | None = None
        self._engine_rpm_ts: float | None = None
        self._last_error: str | None = None
        self._last_raw_response: str | None = None
        self._current_reconnect_delay = _INITIAL_RECONNECT_DELAY_S

    @property
    def speed_mps(self) -> float | None:
        with self._lock:
            return self._speed_snapshot[0]

    @property
    def stale_timeout_s(self) -> float:
        return self._policy.stale_timeout_s

    @property
    def engine_rpm(self) -> float | None:
        with self._lock:
            rpm = self._engine_rpm
            timestamp = self._engine_rpm_ts
            selected_source = self._selected_source
        if selected_source is not SpeedSourceKind.OBD2:
            return None
        if not isinstance(rpm, NUMERIC_TYPES) or isinstance(rpm, bool) or timestamp is None:
            return None
        if (self._monotonic() - timestamp) > self._policy.stale_timeout_s:
            return None
        return float(rpm)

    @property
    def engine_rpm_source(self) -> str | None:
        return "obd2" if self.engine_rpm is not None else None

    def resolve_speed(self) -> SpeedResolution:
        with self._lock:
            connection_state = self._connection_state
            speed_snapshot = self._speed_snapshot
            selected_source = self._selected_source
            snapshot = self._policy.snapshot()
        return self._policy.resolve(
            gps_enabled=selected_source is SpeedSourceKind.OBD2,
            connection_state=connection_state,
            speed_snapshot=speed_snapshot,
            snapshot=snapshot,
            live_source="obd2",
        )

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
        applied_speed = self._policy.apply_speed_source_settings(
            effective_speed_kmh=effective_speed_kmh,
            manual_source_selected=manual_source_selected,
            stale_timeout_s=stale_timeout_s,
        )
        with self._lock:
            if selected_source is not None:
                self._selected_source = SpeedSourceKind(selected_source)
            self._configured_device_mac = obd_device_mac
            self._configured_device_name = obd_device_name
            if (
                self._selected_source is SpeedSourceKind.OBD2
                and self._configured_device_mac is None
            ):
                self._connection_state = "disconnected"
            elif self._selected_source is not SpeedSourceKind.OBD2:
                self._connection_state = "idle"
        return applied_speed

    def scan_devices(self, *, timeout_s: int = 8) -> list[ObdDeviceSnapshot]:
        return self._admin_client.scan_devices(timeout_s=timeout_s)

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        return self._admin_client.pair_device(mac_address)

    def set_manual_source_selected(self, selected: bool) -> None:
        self._policy.set_manual_source_selected(selected)

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        return self._policy.set_speed_override_kmh(speed_kmh)

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None:
        self._policy.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)

    def status_snapshot(self, *, refresh_admin: bool = False) -> ObdStatusSnapshot:
        helper_error: str | None = None
        helper_device: ObdDeviceSnapshot | None = None
        configured_mac: str | None
        with self._lock:
            configured_mac = self._configured_device_mac
        if refresh_admin and configured_mac is not None:
            try:
                helper_device = self._admin_client.device_info(configured_mac)
            except RuntimeError as exc:
                helper_error = str(exc)
            else:
                self._apply_device_snapshot(helper_device)
        with self._lock:
            speed_mps, last_speed_ts = self._speed_snapshot
            now = self._monotonic()
            last_speed_age_s = None if last_speed_ts is None else round(now - last_speed_ts, 2)
            last_speed_kmh = None
            if isinstance(speed_mps, NUMERIC_TYPES) and not isinstance(speed_mps, bool):
                last_speed_kmh = round(float(speed_mps) * MPS_TO_KMH, 2)
            current_error = self._last_error or helper_error
            reconnect_delay = (
                round(self._current_reconnect_delay, 1)
                if self._connection_state == "disconnected"
                else None
            )
            device_name = self._device_name
            configured_name = self._configured_device_name
            helper_name = helper_device.name if helper_device is not None else None
            effective_name = device_name or configured_name or helper_name
            return ObdStatusSnapshot(
                configured_device_mac=self._configured_device_mac,
                configured_device_name=configured_name,
                connection_state=self._effective_connection_state_unlocked(),
                device_mac=self._device_mac or self._configured_device_mac,
                device_name=effective_name,
                paired=self._paired,
                trusted=self._trusted,
                connected=self._device_connected,
                rfcomm_channel=self._rfcomm_channel,
                last_sample_age_s=last_speed_age_s,
                last_speed_kmh=last_speed_kmh,
                last_rpm=self.engine_rpm,
                last_error=current_error,
                last_raw_response=self._last_raw_response,
                reconnect_delay_s=reconnect_delay,
                debug_hint=self._debug_hint_unlocked(helper_error=helper_error),
            )

    async def run(self) -> None:
        session: Elm327Session | None = None
        session_device_mac: str | None = None
        reconnect_delay = _INITIAL_RECONNECT_DELAY_S
        try:
            while True:
                selected_source, configured_mac, configured_name = self._config_snapshot()
                if selected_source is not SpeedSourceKind.OBD2:
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    session, session_device_mac = await self._idle(session, session_device_mac)
                    await asyncio.sleep(_IDLE_POLL_S)
                    continue
                if configured_mac is None:
                    self._set_connection_state(
                        "disconnected",
                        error="No configured Bluetooth OBD adapter",
                    )
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    session, session_device_mac = await self._idle(session, session_device_mac)
                    await asyncio.sleep(_IDLE_POLL_S)
                    continue
                if session is not None and session_device_mac != configured_mac:
                    await asyncio.to_thread(session.close)
                    session = None
                    session_device_mac = None
                if session is None:
                    self._set_connection_state("connecting", error=None)
                    try:
                        session, device = await asyncio.to_thread(
                            self._connect_blocking,
                            configured_mac,
                            configured_name,
                        )
                    except RuntimeError as exc:
                        self._set_connection_state(
                            "disconnected",
                            error=str(exc),
                            reconnect_delay_s=reconnect_delay,
                        )
                        await asyncio.sleep(reconnect_delay)
                        reconnect_delay = min(reconnect_delay * 2.0, _MAX_RECONNECT_DELAY_S)
                        continue
                    session_device_mac = device.mac_address
                    reconnect_delay = _INITIAL_RECONNECT_DELAY_S
                    self._apply_device_snapshot(device)
                    self._set_connection_state("connected", error=None)
                assert session is not None
                try:
                    poll_result = await asyncio.to_thread(self._poll_cycle_blocking, session)
                except RuntimeError as exc:
                    assert session is not None
                    await asyncio.to_thread(session.close)
                    session = None
                    session_device_mac = None
                    self._set_connection_state(
                        "disconnected",
                        error=str(exc),
                        reconnect_delay_s=reconnect_delay,
                    )
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2.0, _MAX_RECONNECT_DELAY_S)
                    continue
                self._apply_poll_result(poll_result)
                await asyncio.sleep(self._poll_interval_s)
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
            raise RuntimeError("Configured OBD adapter is not paired")
        if not info.trusted:
            raise RuntimeError("Configured OBD adapter is not trusted")
        if info.rfcomm_channel is None:
            raise RuntimeError("Bluetooth OBD adapter exposes no RFCOMM serial channel")
        session = self._session_factory()
        session.connect(mac_address, info.rfcomm_channel)
        try:
            session.initialize()
        except Exception:
            session.close()
            raise
        device = replace(
            info,
            name=info.name or configured_name,
            connected=True,
        )
        return session, device

    def _poll_cycle_blocking(self, session: Elm327Session) -> _PollResult:
        try:
            speed_raw = session.request("010D")
        except ObdTransportError as exc:
            raise RuntimeError(str(exc)) from exc
        speed_kmh = parse_pid_010d_speed_kmh(speed_raw)
        speed_error: str | None = None
        if speed_kmh is None:
            if elm_response_has_no_data(speed_raw):
                speed_error = "ECU returned no speed data for PID 010D"
            else:
                speed_error = f"Unexpected speed response for PID 010D: {speed_raw or '<empty>'}"
        rpm_raw: str | None = None
        rpm: float | None = None
        try:
            rpm_raw = session.request("010C")
        except ObdTransportError:
            rpm_raw = None
        else:
            rpm = parse_pid_010c_rpm(rpm_raw)
        raw_parts = [part for part in (speed_raw, rpm_raw) if part]
        return _PollResult(
            speed_mps=(speed_kmh * KMH_TO_MPS) if speed_kmh is not None else None,
            speed_error=speed_error,
            rpm=rpm,
            raw_response=" | ".join(raw_parts) if raw_parts else None,
        )

    def _apply_poll_result(self, result: _PollResult) -> None:
        now = self._monotonic()
        with self._lock:
            if result.speed_mps is not None:
                self._speed_snapshot = (float(result.speed_mps), now)
            if (
                result.rpm is not None
                and isinstance(result.rpm, NUMERIC_TYPES)
                and not isinstance(result.rpm, bool)
            ):
                self._engine_rpm = float(result.rpm)
                self._engine_rpm_ts = now
            else:
                self._engine_rpm = None
                self._engine_rpm_ts = None
            self._last_raw_response = result.raw_response
            self._last_error = result.speed_error
            self._device_connected = True
            self._connection_state = "connected"
            self._current_reconnect_delay = _INITIAL_RECONNECT_DELAY_S

    def _apply_device_snapshot(self, snapshot: ObdDeviceSnapshot) -> None:
        with self._lock:
            self._device_mac = snapshot.mac_address
            self._device_name = snapshot.name
            self._paired = snapshot.paired
            self._trusted = snapshot.trusted
            self._device_connected = snapshot.connected
            self._rfcomm_channel = snapshot.rfcomm_channel

    async def _idle(
        self,
        session: Elm327Session | None,
        session_device_mac: str | None,
    ) -> tuple[Elm327Session | None, str | None]:
        if session is not None:
            await asyncio.to_thread(session.close)
        return None, None

    def _config_snapshot(self) -> tuple[SpeedSourceKind, str | None, str | None]:
        with self._lock:
            return self._selected_source, self._configured_device_mac, self._configured_device_name

    def _set_connection_state(
        self,
        state: str,
        *,
        error: str | None,
        reconnect_delay_s: float | None = None,
    ) -> None:
        with self._lock:
            self._connection_state = state
            self._last_error = error
            self._device_connected = state == "connected"
            if reconnect_delay_s is not None:
                self._current_reconnect_delay = float(reconnect_delay_s)
            elif state == "connected":
                self._current_reconnect_delay = _INITIAL_RECONNECT_DELAY_S

    def _effective_connection_state_unlocked(self) -> str:
        return self._policy.effective_connection_state(
            gps_enabled=self._selected_source is SpeedSourceKind.OBD2,
            actual_connection_state=self._connection_state,
            speed_snapshot=self._speed_snapshot,
        )

    def _debug_hint_unlocked(self, *, helper_error: str | None) -> str | None:
        if helper_error is not None:
            if "password" in helper_error.lower() or "sudo" in helper_error.lower():
                return "Install the Bluetooth OBD sudo helper and NOPASSWD sudoers entry on the Pi."
            return (
                "Bluetooth admin helper failed; try scan/pair again after "
                "power-cycling the adapter."
            )
        if self._configured_device_mac is None:
            return (
                "Pair a Bluetooth OBD adapter in Settings before selecting "
                "OBD-II as the speed source."
            )
        if not self._paired:
            return (
                "Re-run Bluetooth pairing; the configured adapter is no longer paired with the Pi."
            )
        if not self._trusted:
            return (
                "Trust the configured OBD adapter again so reconnects can succeed without prompts."
            )
        if self._rfcomm_channel is None:
            return (
                "Rescan the adapter after power-cycling it; no RFCOMM serial "
                "channel was advertised."
            )
        if self._connection_state == "disconnected":
            return (
                "Keep the adapter powered and in range; VibeSensor will keep "
                "retrying automatically."
            )
        return None
