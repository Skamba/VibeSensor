"""Settings-driven control surface for Bluetooth OBD runtime policy."""

from __future__ import annotations

from vibesensor.domain import SpeedSourceKind

from .runtime_control import apply_runtime_control_decision, resolve_runtime_control_decision
from .runtime_store import ObdRuntimeStore

__all__ = ["ObdRuntimeSettings"]


class ObdRuntimeSettings:
    """Apply speed-source settings and the runtime-side resets they imply."""

    __slots__ = ("_store",)

    def __init__(self, *, store: ObdRuntimeStore) -> None:
        self._store = store

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
        with self._store._lock:
            update = self._store.policy.apply_speed_source_settings(
                effective_speed_kmh=effective_speed_kmh,
                manual_source_selected=manual_source_selected,
                stale_timeout_s=stale_timeout_s,
                selected_source=selected_source,
                obd_device_mac=obd_device_mac,
                obd_device_name=obd_device_name,
            )
            apply_runtime_control_decision(
                self._store.state,
                resolve_runtime_control_decision(update),
            )
            return update.applied_speed_kmh

    def set_manual_source_selected(self, selected: bool) -> None:
        with self._store._lock:
            self._store.policy.set_manual_source_selected(selected)

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        with self._store._lock:
            return self._store.policy.set_speed_override_kmh(speed_kmh)

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None:
        with self._store._lock:
            self._store.policy.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)
