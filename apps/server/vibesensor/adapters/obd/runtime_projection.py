"""Policy-derived Bluetooth OBD status and speed projection over runtime facts."""

from __future__ import annotations

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.obd.models import ObdStatusSnapshot
from vibesensor.adapters.obd.status import build_obd_status_snapshot
from vibesensor.shared.timed_observation import (
    DEFAULT_ALIGNMENT_TOLERANCE_S,
    TimedObservationLookup,
    TimedScalarObservation,
    resolve_timed_observation,
)
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeProjection"]


class ObdRuntimeProjection:
    """Project effective OBD status and speed from raw facts plus policy."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

    @property
    def stale_timeout_s(self) -> float:
        with self._store._lock:
            return self._store.policy.stale_timeout_s

    def resolve_speed(self) -> SpeedResolution:
        with self._store._lock:
            return self._store.policy.resolve_speed(
                connection_state=self._store.state.connection_state,
                speed_snapshot=self._store.state.speed_snapshot,
            )

    def resolve_speed_context_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> AlignedSpeedContextSnapshot:
        with self._store._lock:
            history = self._store.state.speed_history
            if not history and self._store.state.speed_snapshot[0] is not None:
                speed_value, speed_time = self._store.state.speed_snapshot
                if speed_value is not None and speed_time is not None:
                    history = (
                        TimedScalarObservation(
                            value=float(speed_value),
                            monotonic_s=float(speed_time),
                        ),
                    )
            lookup = self._lookup_speed_observation(
                history=history,
                target_mono_s=target_mono_s,
                tolerance_s=tolerance_s,
            )
            resolution = self._store.policy.resolve_speed(
                connection_state=self._store.state.connection_state,
                speed_snapshot=(lookup.value, lookup.monotonic_s),
                reference_time_s=target_mono_s,
            )
        resolved_aligned = (
            resolution.source == "obd2" and lookup.aligned and resolution.speed_mps is not None
        ) or (
            resolution.source in {"manual", "fallback_manual"} and resolution.speed_mps is not None
        )
        return AlignedSpeedContextSnapshot(
            selected_speed_source="obd2",
            resolved_speed_mps=resolution.speed_mps,
            resolved_speed_source=resolution.source,
            resolved_speed_aligned=resolved_aligned,
            gps_speed_mps=None,
            gps_speed_aligned=False,
            measured_engine_rpm=None,
            measured_engine_rpm_source=None,
            measured_engine_rpm_aligned=False,
        )

    def status_snapshot(self) -> ObdStatusSnapshot:
        now = self._store.monotonic()
        with self._store._lock:
            return build_obd_status_snapshot(
                self._store.state.status_facts(
                    engine_rpm=self._store.state.engine_rpm(now=now),
                    polling=self._store.polling,
                ),
                configured_device_mac=self._store.policy.configured_device_mac,
                configured_device_name=self._store.policy.configured_device_name,
                effective_connection_state=self._store.policy.effective_connection_state(
                    connection_state=self._store.state.connection_state,
                    speed_snapshot=self._store.state.speed_snapshot,
                ),
                obd_selected=self._store.policy.obd_selected,
                now_mono=now,
            )

    @staticmethod
    def _lookup_speed_observation(
        *,
        history: tuple[TimedScalarObservation, ...],
        target_mono_s: float | None,
        tolerance_s: float | None,
    ) -> TimedObservationLookup:
        if target_mono_s is None:
            return TimedObservationLookup(value=None, monotonic_s=None, aligned=False)
        return resolve_timed_observation(
            history,
            target_mono_s=target_mono_s,
            tolerance_s=(
                DEFAULT_ALIGNMENT_TOLERANCE_S if tolerance_s is None else float(tolerance_s)
            ),
        )
