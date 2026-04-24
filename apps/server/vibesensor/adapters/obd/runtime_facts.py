"""Raw observed Bluetooth OBD facts over shared runtime state."""

from __future__ import annotations

from vibesensor.shared.timed_observation import (
    DEFAULT_ALIGNMENT_TOLERANCE_S,
    TimedObservationLookup,
    TimedScalarObservation,
    resolve_timed_observation,
)

from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeFacts"]


class ObdRuntimeFacts:
    """Read live OBD facts without applying selected-source policy."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

    @property
    def speed_mps(self) -> float | None:
        with self._store._lock:
            return self._store.state.speed_mps

    @property
    def engine_rpm(self) -> float | None:
        now = self._store.monotonic()
        with self._store._lock:
            return self._store.state.engine_rpm(now=now)

    @property
    def engine_rpm_source(self) -> str | None:
        return "obd2" if self.engine_rpm is not None else None

    def engine_rpm_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> TimedObservationLookup:
        with self._store._lock:
            history = self._store.state.engine_rpm_history
            now = self._store.monotonic()
            rpm = self._store.state.engine_rpm(now=now)
            rpm_ts = self._store.state.engine_rpm_ts
            if not history and rpm is not None:
                if rpm is not None and rpm_ts is not None:
                    history = (
                        TimedScalarObservation(
                            value=float(rpm),
                            monotonic_s=float(rpm_ts),
                        ),
                    )
        if target_mono_s is None:
            return TimedObservationLookup(value=None, monotonic_s=None, aligned=False)
        return resolve_timed_observation(
            history,
            target_mono_s=target_mono_s,
            tolerance_s=(
                DEFAULT_ALIGNMENT_TOLERANCE_S if tolerance_s is None else float(tolerance_s)
            ),
        )
