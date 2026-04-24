"""GPS speed monitor facade over transport, policy, and status presentation."""

from __future__ import annotations

from typing import Literal

from vibesensor.adapters.gps import speed_resolution as _speed_resolution
from vibesensor.adapters.gps.gps_transport import (
    GPSTransportCapturedState,
    GPSTransportSnapshot,
    GPSTransportState,
)
from vibesensor.adapters.gps.gpsd_message_handler import (
    read_non_negative_metric,
    read_tpv_mode,
)
from vibesensor.adapters.gps.speed_resolution import (
    SpeedResolution,
    SpeedResolutionPolicy,
    SpeedResolutionPolicySnapshot,
)
from vibesensor.adapters.gps.speed_status import (
    GPSSpeedStatusState,
    SpeedSourceStatusSnapshot,
    build_status_snapshot,
    speed_confidence,
)
from vibesensor.shared.timed_observation import (
    DEFAULT_ALIGNMENT_TOLERANCE_S,
    TimedObservationLookup,
    TimedScalarObservation,
    resolve_timed_observation,
)
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot
from vibesensor.shared.types.json_types import JsonObject

DEFAULT_STALE_TIMEOUT_S = _speed_resolution.DEFAULT_STALE_TIMEOUT_S
MIN_STALE_TIMEOUT_S = _speed_resolution.MIN_STALE_TIMEOUT_S
MAX_STALE_TIMEOUT_S = _speed_resolution.MAX_STALE_TIMEOUT_S
MAX_MANUAL_SPEED_KMH = _speed_resolution.MAX_MANUAL_SPEED_KMH

__all__ = ["GPSSpeedMonitor", "SpeedResolution"]


class GPSSpeedMonitor:
    """Runtime-facing GPS monitor over captured transport/policy snapshots.

    Writers replace immutable transport/policy snapshots atomically; readers
    capture those snapshots once per resolution/status read so concurrent async
    ingest and threaded settings updates cannot expose half-applied state.
    """

    def __init__(self, gps_enabled: bool):
        self._transport = GPSTransportState(gps_enabled=gps_enabled)
        self._policy = SpeedResolutionPolicy()

    @property
    def gps_enabled(self) -> bool:
        return self._transport.gps_enabled

    @gps_enabled.setter
    def gps_enabled(self, value: bool) -> None:
        self._transport.set_enabled(bool(value))

    @property
    def override_speed_mps(self) -> float | None:
        return self._policy.override_speed_mps

    @override_speed_mps.setter
    def override_speed_mps(self, value: float | None) -> None:
        self._policy.override_speed_mps = value

    @property
    def manual_source_selected(self) -> bool:
        return self._policy.manual_source_selected

    @manual_source_selected.setter
    def manual_source_selected(self, value: bool) -> None:
        self._policy.manual_source_selected = bool(value)

    @property
    def stale_timeout_s(self) -> float:
        return self._policy.stale_timeout_s

    @stale_timeout_s.setter
    def stale_timeout_s(self, value: float) -> None:
        self._policy.stale_timeout_s = float(value)

    @property
    def connection_state(self) -> str:
        return self._transport.connection_state

    @connection_state.setter
    def connection_state(self, value: str) -> None:
        self._transport.connection_state = value

    @property
    def speed_mps(self) -> float | None:
        return self._transport.speed_mps

    @speed_mps.setter
    def speed_mps(self, value: float | None) -> None:
        self._transport.speed_mps = value

    @property
    def _speed_snapshot(self) -> tuple[float | None, float | None]:
        return self._transport._speed_snapshot

    @_speed_snapshot.setter
    def _speed_snapshot(self, value: tuple[float | None, float | None]) -> None:
        self._transport._speed_snapshot = value

    @property
    def last_error(self) -> str | None:
        return self._transport.last_error

    @last_error.setter
    def last_error(self, value: str | None) -> None:
        self._transport.last_error = value

    @property
    def current_reconnect_delay(self) -> float:
        return self._transport.current_reconnect_delay

    @current_reconnect_delay.setter
    def current_reconnect_delay(self, value: float) -> None:
        self._transport.current_reconnect_delay = value

    @property
    def device_info(self) -> str | None:
        return self._transport.device_info

    @device_info.setter
    def device_info(self, value: str | None) -> None:
        self._transport.device_info = value

    @property
    def last_fix_mode(self) -> int | None:
        return self._transport.last_fix_mode

    @last_fix_mode.setter
    def last_fix_mode(self, value: int | None) -> None:
        self._transport.last_fix_mode = value

    @property
    def last_epx_m(self) -> float | None:
        return self._transport.last_epx_m

    @last_epx_m.setter
    def last_epx_m(self, value: float | None) -> None:
        self._transport.last_epx_m = value

    @property
    def last_epy_m(self) -> float | None:
        return self._transport.last_epy_m

    @last_epy_m.setter
    def last_epy_m(self, value: float | None) -> None:
        self._transport.last_epy_m = value

    @property
    def last_epv_m(self) -> float | None:
        return self._transport.last_epv_m

    @last_epv_m.setter
    def last_epv_m(self, value: float | None) -> None:
        self._transport.last_epv_m = value

    @property
    def _zero_speed_streak(self) -> int:
        return self._transport._zero_speed_streak

    @_zero_speed_streak.setter
    def _zero_speed_streak(self, value: int) -> None:
        self._transport._zero_speed_streak = value

    @property
    def effective_speed_mps(self) -> float | None:
        return self.resolve_speed().speed_mps

    @property
    def gps_speed_mps(self) -> float | None:
        return self.speed_mps

    @property
    def engine_rpm(self) -> float | None:
        return None

    @property
    def engine_rpm_source(self) -> str | None:
        return None

    @property
    def fallback_active(self) -> bool:
        return self.resolve_speed().fallback_active

    @property
    def last_update_ts(self) -> float | None:
        return self._transport.last_update_ts

    def resolve_speed(self) -> SpeedResolution:
        transport_snapshot, policy_snapshot = self._captured_snapshots()
        return self._policy.resolve(
            gps_enabled=transport_snapshot.gps_enabled,
            connection_state=transport_snapshot.connection_state,
            speed_snapshot=transport_snapshot.speed_snapshot,
            snapshot=policy_snapshot,
        )

    def resolve_speed_context_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> AlignedSpeedContextSnapshot:
        transport_snapshot, policy_snapshot = self._captured_snapshots()
        selected_source: Literal["gps", "manual"] = (
            "manual" if policy_snapshot.manual_source_selected else "gps"
        )
        raw_speed = self._speed_observation_at(
            transport_snapshot=transport_snapshot,
            target_mono_s=target_mono_s,
            tolerance_s=tolerance_s,
        )
        resolution = self._policy.resolve(
            gps_enabled=transport_snapshot.gps_enabled,
            connection_state=transport_snapshot.connection_state,
            speed_snapshot=(raw_speed.value, raw_speed.monotonic_s),
            snapshot=policy_snapshot,
            live_source="gps",
            reference_time_s=target_mono_s,
        )
        resolved_aligned = (
            resolution.source in {"manual", "fallback_manual"} and resolution.speed_mps is not None
        ) or (resolution.source == "gps" and raw_speed.aligned and resolution.speed_mps is not None)
        return AlignedSpeedContextSnapshot(
            selected_speed_source=selected_source,
            resolved_speed_mps=resolution.speed_mps,
            resolved_speed_source=resolution.source,
            resolved_speed_aligned=resolved_aligned,
            gps_speed_mps=raw_speed.value if raw_speed.aligned else None,
            gps_speed_aligned=raw_speed.aligned,
            measured_engine_rpm=None,
            measured_engine_rpm_source=None,
            measured_engine_rpm_aligned=False,
        )

    def _effective_connection_state(self) -> str:
        transport_snapshot, policy_snapshot = self._captured_snapshots()
        return self._policy.effective_connection_state(
            gps_enabled=transport_snapshot.gps_enabled,
            actual_connection_state=transport_snapshot.connection_state,
            speed_snapshot=transport_snapshot.speed_snapshot,
            snapshot=policy_snapshot,
        )

    def _is_gps_stale(self) -> bool:
        transport_snapshot, policy_snapshot = self._captured_snapshots()
        return self._policy.is_gps_stale(
            transport_snapshot.speed_snapshot,
            snapshot=policy_snapshot,
        )

    def _fallback_speed_value(self) -> float | None:
        _, policy_snapshot = self._captured_snapshots()
        return self._policy.fallback_speed_value(snapshot=policy_snapshot)

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        return self._policy.set_speed_override_kmh(speed_kmh)

    def set_manual_source_selected(self, selected: bool) -> None:
        self._policy.set_manual_source_selected(selected)

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None:
        self._policy.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)

    def apply_speed_source_settings(
        self,
        *,
        effective_speed_kmh: float | None,
        manual_source_selected: bool,
        stale_timeout_s: float | None = None,
    ) -> float | None:
        """Apply the full speed-source config atomically for concurrent readers."""
        return self._policy.apply_speed_source_settings(
            effective_speed_kmh=effective_speed_kmh,
            manual_source_selected=manual_source_selected,
            stale_timeout_s=stale_timeout_s,
        )

    @staticmethod
    def _read_non_negative_metric(payload: JsonObject, field: str) -> float | None:
        return read_non_negative_metric(payload, field)

    @staticmethod
    def _tpv_mode(payload: JsonObject) -> int | None:
        return read_tpv_mode(payload)

    def _speed_confidence(self) -> Literal["low", "medium", "high"]:
        return speed_confidence(self.last_fix_mode, self.last_epx_m, self.last_epy_m)

    def _accept_speed_sample(self, speed_mps: float) -> bool:
        return self._transport._accept_speed_sample(speed_mps)

    def _reset_fix_metadata(self) -> None:
        self._transport._reset_fix_metadata()

    def _captured_snapshots(
        self,
    ) -> tuple[GPSTransportSnapshot, SpeedResolutionPolicySnapshot]:
        return self._transport.snapshot(), self._policy.snapshot()

    def _captured_status_snapshots(
        self,
    ) -> tuple[GPSTransportCapturedState, SpeedResolutionPolicySnapshot]:
        return self._transport.captured_state(), self._policy.snapshot()

    def _speed_observation_at(
        self,
        *,
        transport_snapshot: GPSTransportSnapshot,
        target_mono_s: float | None,
        tolerance_s: float | None,
    ) -> TimedObservationLookup:
        if target_mono_s is None:
            return TimedObservationLookup(value=None, monotonic_s=None, aligned=False)
        history = transport_snapshot.speed_history
        if not history and transport_snapshot.speed_snapshot[0] is not None:
            speed_value, speed_time = transport_snapshot.speed_snapshot
            if speed_value is not None and speed_time is not None:
                history = (
                    TimedScalarObservation(
                        value=float(speed_value),
                        monotonic_s=float(speed_time),
                    ),
                )
        return resolve_timed_observation(
            history,
            target_mono_s=target_mono_s,
            tolerance_s=(
                DEFAULT_ALIGNMENT_TOLERANCE_S if tolerance_s is None else float(tolerance_s)
            ),
        )

    def status_snapshot(self) -> SpeedSourceStatusSnapshot:
        captured_state, policy_snapshot = self._captured_status_snapshots()
        transport_snapshot = captured_state.transport
        lifecycle_snapshot = captured_state.lifecycle
        speed_snapshot = transport_snapshot.speed_snapshot
        resolution = self._policy.resolve(
            gps_enabled=transport_snapshot.gps_enabled,
            connection_state=transport_snapshot.connection_state,
            speed_snapshot=speed_snapshot,
            snapshot=policy_snapshot,
        )
        status_state = GPSSpeedStatusState(
            gps_enabled=transport_snapshot.gps_enabled,
            connection_state=transport_snapshot.connection_state,
            device_info=transport_snapshot.device_info,
            last_fix_mode=transport_snapshot.last_fix_mode,
            last_epx_m=transport_snapshot.last_epx_m,
            last_epy_m=transport_snapshot.last_epy_m,
            last_epv_m=transport_snapshot.last_epv_m,
            raw_speed_mps=speed_snapshot[0],
            last_update_ts=speed_snapshot[1],
            last_error=lifecycle_snapshot.last_error,
            current_reconnect_delay=lifecycle_snapshot.current_reconnect_delay,
            stale_timeout_s=policy_snapshot.stale_timeout_s,
        )
        return build_status_snapshot(
            status_state,
            resolution=resolution,
            effective_connection_state=self._policy.effective_connection_state(
                gps_enabled=transport_snapshot.gps_enabled,
                actual_connection_state=transport_snapshot.connection_state,
                speed_snapshot=speed_snapshot,
                snapshot=policy_snapshot,
            ),
        )

    async def run(self, host: str = "127.0.0.1", port: int = 2947) -> None:
        await self._transport.run(
            host=host,
            port=port,
            tpv_mode=self._tpv_mode,
            read_metric=self._read_non_negative_metric,
        )
