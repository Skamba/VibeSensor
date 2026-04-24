"""Observed runtime state for Bluetooth OBD monitoring."""

from __future__ import annotations

from vibesensor.adapters.obd.admin_state import ObdAdminObservation
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.polling import ObdPidPollResult, ObdPollingCadence, ObdPollResult
from vibesensor.adapters.obd.status import ObdRuntimeStatusFacts
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import KMH_TO_MPS
from vibesensor.shared.timed_observation import TimedScalarObservation, append_timed_observation

__all__ = ["ObdRuntimeState"]


class ObdRuntimeState:
    """Own live OBD observations independently from configuration and policy."""

    __slots__ = (
        "_connection_state",
        "_current_reconnect_delay",
        "_device_connected",
        "_device_mac",
        "_device_name",
        "_engine_rpm",
        "_engine_rpm_stale_timeout_s",
        "_engine_rpm_history",
        "_engine_rpm_ts",
        "_initial_reconnect_delay_s",
        "_last_admin_error",
        "_last_error",
        "_paired",
        "_rfcomm_channel",
        "_speed_snapshot",
        "_speed_history",
        "_trusted",
    )

    def __init__(
        self,
        *,
        initial_reconnect_delay_s: float,
        engine_rpm_stale_timeout_s: float,
    ) -> None:
        self._initial_reconnect_delay_s = initial_reconnect_delay_s
        self._engine_rpm_stale_timeout_s = engine_rpm_stale_timeout_s
        self._connection_state = "idle"
        self._current_reconnect_delay = initial_reconnect_delay_s
        self._device_connected = False
        self._device_mac: str | None = None
        self._device_name: str | None = None
        self._engine_rpm: float | None = None
        self._engine_rpm_history: tuple[TimedScalarObservation, ...] = ()
        self._engine_rpm_ts: float | None = None
        self._last_admin_error: str | None = None
        self._last_error: str | None = None
        self._paired = False
        self._rfcomm_channel: int | None = None
        self._speed_snapshot: tuple[float | None, float | None] = (None, None)
        self._speed_history: tuple[TimedScalarObservation, ...] = ()
        self._trusted = False

    @property
    def connection_state(self) -> str:
        return self._connection_state

    @property
    def speed_snapshot(self) -> tuple[float | None, float | None]:
        return self._speed_snapshot

    @speed_snapshot.setter
    def speed_snapshot(self, value: tuple[float | None, float | None]) -> None:
        self._speed_snapshot = value

    @property
    def speed_history(self) -> tuple[TimedScalarObservation, ...]:
        return self._speed_history

    @property
    def speed_mps(self) -> float | None:
        return self._speed_snapshot[0]

    @property
    def engine_rpm_ts(self) -> float | None:
        return self._engine_rpm_ts

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def engine_rpm(self, *, now: float) -> float | None:
        if (
            not isinstance(self._engine_rpm, NUMERIC_TYPES)
            or isinstance(self._engine_rpm, bool)
            or self._engine_rpm_ts is None
        ):
            return None
        if (now - self._engine_rpm_ts) > self._engine_rpm_stale_timeout_s:
            return None
        return float(self._engine_rpm)

    def apply_poll_result(
        self,
        result: ObdPollResult,
        *,
        now: float,
        polling: ObdPollingCadence,
    ) -> None:
        polling.apply_result(result, now=now)
        if (
            result.speed.value is not None
            and isinstance(result.speed.value, NUMERIC_TYPES)
            and not isinstance(result.speed.value, bool)
        ):
            speed_sample_time = self._completed_at(result.speed, fallback_now=now)
            self._speed_snapshot = (float(result.speed.value) * KMH_TO_MPS, speed_sample_time)
            self._speed_history = append_timed_observation(
                self._speed_history,
                value=float(result.speed.value) * KMH_TO_MPS,
                monotonic_s=speed_sample_time,
                now_s=now,
            )
        if (
            result.rpm.value is not None
            and isinstance(result.rpm.value, NUMERIC_TYPES)
            and not isinstance(result.rpm.value, bool)
        ):
            rpm_sample_time = self._completed_at(result.rpm, fallback_now=now)
            self._engine_rpm = float(result.rpm.value)
            self._engine_rpm_ts = rpm_sample_time
            self._engine_rpm_history = append_timed_observation(
                self._engine_rpm_history,
                value=float(result.rpm.value),
                monotonic_s=rpm_sample_time,
                now_s=now,
            )
        self._last_error = result.rpm.error or result.speed.error
        if result.connection_lost:
            return
        self._device_connected = True
        self._connection_state = "connected"
        self._current_reconnect_delay = self._initial_reconnect_delay_s

    def apply_device_snapshot(self, snapshot: ObdDeviceSnapshot) -> None:
        self._device_mac = snapshot.mac_address
        self._device_name = snapshot.name
        self._paired = snapshot.paired
        self._trusted = snapshot.trusted
        self._device_connected = snapshot.connected
        self._rfcomm_channel = snapshot.rfcomm_channel
        self._last_admin_error = None

    def apply_admin_observation(
        self,
        *,
        observed_configured_mac: str | None,
        current_configured_mac: str | None,
        observation: ObdAdminObservation,
    ) -> None:
        if observed_configured_mac != current_configured_mac:
            return
        self._last_admin_error = observation.helper_error
        if observation.snapshot is not None:
            self.apply_device_snapshot(observation.snapshot)

    def set_connection_state(
        self,
        state: str,
        *,
        error: str | None,
        reconnect_delay_s: float | None = None,
    ) -> None:
        self._connection_state = state
        self._last_error = error
        self._device_connected = state == "connected"
        if reconnect_delay_s is not None:
            self._current_reconnect_delay = float(reconnect_delay_s)
        elif state == "connected":
            self._current_reconnect_delay = self._initial_reconnect_delay_s

    def reset_observed_device_state(self, *, clear_runtime_error: bool) -> None:
        self._device_mac = None
        self._device_name = None
        self._paired = False
        self._trusted = False
        self._device_connected = False
        self._rfcomm_channel = None
        self._last_admin_error = None
        if clear_runtime_error:
            self._last_error = None

    def status_facts(
        self,
        *,
        engine_rpm: float | None,
        polling: ObdPollingCadence,
    ) -> ObdRuntimeStatusFacts:
        return ObdRuntimeStatusFacts(
            transport_connection_state=self._connection_state,
            device_mac=self._device_mac,
            device_name=self._device_name,
            paired=self._paired,
            trusted=self._trusted,
            connected=self._device_connected,
            rfcomm_channel=self._rfcomm_channel,
            speed_snapshot=self._speed_snapshot,
            engine_rpm=engine_rpm,
            engine_rpm_ts=self._engine_rpm_ts,
            last_runtime_error=self._last_error,
            helper_error=self._last_admin_error,
            reconnect_delay_s=self._current_reconnect_delay,
            polling=polling.snapshot(),
        )

    @property
    def engine_rpm_history(self) -> tuple[TimedScalarObservation, ...]:
        return self._engine_rpm_history

    @staticmethod
    def _completed_at(result: ObdPidPollResult, *, fallback_now: float) -> float:
        if result.started_at_s is not None and result.duration_s is not None:
            return result.started_at_s + result.duration_s
        return fallback_now
