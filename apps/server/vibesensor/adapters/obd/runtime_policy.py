"""Policy/configuration state for Bluetooth OBD runtime monitoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic as default_monotonic

from vibesensor.adapters.gps.speed_resolution import SpeedResolution, SpeedResolutionPolicy
from vibesensor.domain import SpeedSourceKind

__all__ = ["ObdPolicyUpdate", "ObdRuntimePolicy"]


@dataclass(frozen=True, slots=True)
class ObdPolicyUpdate:
    """One applied configuration change for the OBD runtime policy."""

    applied_speed_kmh: float | None
    selected_source: SpeedSourceKind
    configured_device_changed: bool
    configured_device_missing: bool

    @property
    def obd_selected(self) -> bool:
        return self.selected_source is SpeedSourceKind.OBD2


class ObdRuntimePolicy:
    """Own configuration and speed-resolution policy independently from live observations."""

    __slots__ = (
        "_configured_device_mac",
        "_configured_device_name",
        "_selected_source",
        "_speed_policy",
    )

    def __init__(self, *, monotonic: Callable[[], float] = default_monotonic) -> None:
        self._speed_policy = SpeedResolutionPolicy(
            manual_source_selected=False,
            monotonic=monotonic,
        )
        self._selected_source = SpeedSourceKind.GPS
        self._configured_device_mac: str | None = None
        self._configured_device_name: str | None = None

    @property
    def stale_timeout_s(self) -> float:
        return self._speed_policy.stale_timeout_s

    @property
    def selected_source(self) -> SpeedSourceKind:
        return self._selected_source

    @property
    def configured_device_mac(self) -> str | None:
        return self._configured_device_mac

    @property
    def configured_device_name(self) -> str | None:
        return self._configured_device_name

    @property
    def obd_selected(self) -> bool:
        return self._selected_source is SpeedSourceKind.OBD2

    def config_snapshot(self) -> tuple[SpeedSourceKind, str | None, str | None]:
        return (
            self._selected_source,
            self._configured_device_mac,
            self._configured_device_name,
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
    ) -> ObdPolicyUpdate:
        applied_speed_kmh = self._speed_policy.apply_speed_source_settings(
            effective_speed_kmh=effective_speed_kmh,
            manual_source_selected=manual_source_selected,
            stale_timeout_s=stale_timeout_s,
        )
        previous_configured_mac = self._configured_device_mac
        if selected_source is not None:
            self._selected_source = SpeedSourceKind(selected_source)
        self._configured_device_mac = obd_device_mac
        self._configured_device_name = obd_device_name
        return ObdPolicyUpdate(
            applied_speed_kmh=applied_speed_kmh,
            selected_source=self._selected_source,
            configured_device_changed=self._configured_device_mac != previous_configured_mac,
            configured_device_missing=(
                self._selected_source is SpeedSourceKind.OBD2
                and self._configured_device_mac is None
            ),
        )

    def resolve_speed(
        self,
        *,
        connection_state: str,
        speed_snapshot: tuple[float | None, float | None],
        reference_time_s: float | None = None,
    ) -> SpeedResolution:
        return self._speed_policy.resolve(
            gps_enabled=self._selected_source is SpeedSourceKind.OBD2,
            connection_state=connection_state,
            speed_snapshot=speed_snapshot,
            live_source="obd2",
            reference_time_s=reference_time_s,
        )

    def effective_connection_state(
        self,
        *,
        connection_state: str,
        speed_snapshot: tuple[float | None, float | None],
        reference_time_s: float | None = None,
    ) -> str:
        return self._speed_policy.effective_connection_state(
            gps_enabled=self._selected_source is SpeedSourceKind.OBD2,
            actual_connection_state=connection_state,
            speed_snapshot=speed_snapshot,
            reference_time_s=reference_time_s,
        )

    def set_manual_source_selected(self, selected: bool) -> None:
        self._speed_policy.set_manual_source_selected(selected)

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        return self._speed_policy.set_speed_override_kmh(speed_kmh)

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None:
        self._speed_policy.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)
