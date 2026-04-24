"""Explicit speed-source observation, control, and OBD admin services."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.domain import SpeedSourceKind
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import MPS_TO_KMH
from vibesensor.shared.ports import SpeedSourceSync
from vibesensor.shared.timed_observation import TimedObservationLookup
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot

__all__ = [
    "SpeedSourceAdminService",
    "SpeedSourceControlService",
    "SpeedSourceObservationService",
    "SpeedSourceServices",
    "build_speed_source_services",
]


class ObdFacts(Protocol):
    @property
    def speed_mps(self) -> float | None: ...

    @property
    def engine_rpm(self) -> float | None: ...

    @property
    def engine_rpm_source(self) -> str | None: ...

    def engine_rpm_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> TimedObservationLookup: ...


class ObdProjection(Protocol):
    @property
    def stale_timeout_s(self) -> float: ...

    def resolve_speed(self) -> SpeedResolution: ...

    def resolve_speed_context_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> AlignedSpeedContextSnapshot: ...

    def status_snapshot(self) -> ObdStatusSnapshot: ...


class ObdDeviceAdmin(Protocol):
    def scan_devices(self, *, timeout_s: int = ...) -> list[ObdDeviceSnapshot]: ...

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot: ...


class ObdConfiguredDeviceRefresher(Protocol):
    def refresh_configured_device(self) -> None: ...


class _SelectedSourceState:
    __slots__ = ("_kind", "_lock")

    def __init__(self) -> None:
        self._kind = SpeedSourceKind.GPS
        self._lock = RLock()

    def get(self) -> SpeedSourceKind:
        with self._lock:
            return self._kind

    def set(self, kind: SpeedSourceKind) -> None:
        with self._lock:
            self._kind = kind


class SpeedSourceObservationService:
    """Read-side view over the selected live speed source."""

    __slots__ = ("_gps_monitor", "_obd_facts", "_obd_projection", "_selected_source")

    def __init__(
        self,
        *,
        gps_monitor: GPSSpeedMonitor,
        obd_facts: ObdFacts,
        obd_projection: ObdProjection,
        selected_source: _SelectedSourceState,
    ) -> None:
        self._gps_monitor = gps_monitor
        self._obd_facts = obd_facts
        self._obd_projection = obd_projection
        self._selected_source = selected_source

    @property
    def speed_mps(self) -> float | None:
        if self._selected_source.get() is SpeedSourceKind.OBD2:
            return self._obd_facts.speed_mps
        return self._gps_monitor.speed_mps

    @property
    def gps_speed_mps(self) -> float | None:
        return self._gps_monitor.speed_mps

    @property
    def engine_rpm(self) -> float | None:
        if self._selected_source.get() is not SpeedSourceKind.OBD2:
            return None
        return self._obd_facts.engine_rpm

    @property
    def engine_rpm_source(self) -> str | None:
        if self._selected_source.get() is not SpeedSourceKind.OBD2:
            return None
        return self._obd_facts.engine_rpm_source

    def resolve_speed(self) -> SpeedResolution:
        if self._selected_source.get() is SpeedSourceKind.OBD2:
            return self._obd_projection.resolve_speed()
        return self._gps_monitor.resolve_speed()

    def resolve_speed_context_at(
        self,
        target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> AlignedSpeedContextSnapshot:
        gps_context = self._gps_monitor.resolve_speed_context_at(
            target_mono_s,
            tolerance_s=tolerance_s,
        )
        if self._selected_source.get() is not SpeedSourceKind.OBD2:
            return gps_context
        obd_context = self._obd_projection.resolve_speed_context_at(
            target_mono_s,
            tolerance_s=tolerance_s,
        )
        rpm_lookup = self._obd_facts.engine_rpm_at(
            target_mono_s,
            tolerance_s=tolerance_s,
        )
        return AlignedSpeedContextSnapshot(
            selected_speed_source=obd_context.selected_speed_source,
            resolved_speed_mps=obd_context.resolved_speed_mps,
            resolved_speed_source=obd_context.resolved_speed_source,
            resolved_speed_aligned=obd_context.resolved_speed_aligned,
            gps_speed_mps=gps_context.gps_speed_mps,
            gps_speed_aligned=gps_context.gps_speed_aligned,
            measured_engine_rpm=rpm_lookup.value if rpm_lookup.aligned else None,
            measured_engine_rpm_source="obd2" if rpm_lookup.aligned else None,
            measured_engine_rpm_aligned=rpm_lookup.aligned,
        )

    def status_snapshot(self) -> SpeedSourceStatusSnapshot:
        if self._selected_source.get() is not SpeedSourceKind.OBD2:
            return self._gps_monitor.status_snapshot()
        resolution = self._obd_projection.resolve_speed()
        obd_status = self._obd_projection.status_snapshot()
        return SpeedSourceStatusSnapshot(
            gps_enabled=self._gps_monitor.gps_enabled,
            connection_state=obd_status.connection_state,
            device=self._format_device(obd_status),
            fix_mode=None,
            fix_dimension="none",
            speed_confidence="high" if obd_status.last_speed_kmh is not None else "low",
            epx_m=None,
            epy_m=None,
            epv_m=None,
            last_update_age_s=obd_status.last_sample_age_s,
            raw_speed_kmh=obd_status.last_speed_kmh,
            effective_speed_kmh=self._effective_speed_kmh(resolution.speed_mps),
            last_error=obd_status.last_error,
            reconnect_delay_s=obd_status.reconnect_delay_s,
            fallback_active=resolution.fallback_active,
            speed_source=resolution.source,
            stale_timeout_s=self._obd_projection.stale_timeout_s,
        )

    def obd_status(self) -> ObdStatusSnapshot:
        return self._obd_projection.status_snapshot()

    @staticmethod
    def _format_device(snapshot: ObdStatusSnapshot) -> str | None:
        if snapshot.device_name and snapshot.device_mac:
            return f"{snapshot.device_name} ({snapshot.device_mac})"
        return snapshot.device_name or snapshot.device_mac

    @staticmethod
    def _effective_speed_kmh(speed_mps: float | None) -> float | None:
        if not isinstance(speed_mps, NUMERIC_TYPES) or isinstance(speed_mps, bool):
            return None
        return round(float(speed_mps) * MPS_TO_KMH, 2)


class SpeedSourceAdminService:
    """Admin-only Bluetooth OBD actions."""

    __slots__ = ("_obd_device_admin", "_obd_status_refresher")

    def __init__(
        self,
        *,
        obd_device_admin: ObdDeviceAdmin,
        obd_status_refresher: ObdConfiguredDeviceRefresher,
    ) -> None:
        self._obd_device_admin = obd_device_admin
        self._obd_status_refresher = obd_status_refresher

    def scan_obd_devices(self, *, timeout_s: int = 8) -> list[ObdDeviceSnapshot]:
        return self._obd_device_admin.scan_devices(timeout_s=timeout_s)

    def pair_obd_device(self, mac_address: str) -> ObdDeviceSnapshot:
        return self._obd_device_admin.pair_device(mac_address)

    def refresh_obd_status(self) -> None:
        self._obd_status_refresher.refresh_configured_device()


class SpeedSourceControlService:
    """Runtime control surface for applying persisted speed-source settings."""

    __slots__ = ("_gps_monitor", "_obd_control", "_selected_source")

    def __init__(
        self,
        *,
        gps_monitor: GPSSpeedMonitor,
        obd_control: SpeedSourceSync,
        selected_source: _SelectedSourceState,
    ) -> None:
        self._gps_monitor = gps_monitor
        self._obd_control = obd_control
        self._selected_source = selected_source

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
        kind = (
            self._selected_source.get()
            if selected_source is None
            else SpeedSourceKind(selected_source)
        )
        self._selected_source.set(kind)
        applied = self._gps_monitor.apply_speed_source_settings(
            effective_speed_kmh=effective_speed_kmh,
            manual_source_selected=manual_source_selected,
            stale_timeout_s=stale_timeout_s,
        )
        self._obd_control.apply_speed_source_settings(
            effective_speed_kmh=effective_speed_kmh,
            manual_source_selected=manual_source_selected,
            stale_timeout_s=stale_timeout_s,
            selected_source=kind,
            obd_device_mac=obd_device_mac,
            obd_device_name=obd_device_name,
        )
        return applied

    def set_manual_source_selected(self, selected: bool) -> None:
        self._gps_monitor.set_manual_source_selected(selected)
        self._obd_control.set_manual_source_selected(selected)

    def set_speed_override_kmh(self, speed_kmh: float | None) -> float | None:
        applied = self._gps_monitor.set_speed_override_kmh(speed_kmh)
        self._obd_control.set_speed_override_kmh(speed_kmh)
        return applied

    def set_fallback_settings(
        self,
        stale_timeout_s: float | None = None,
        **kwargs: object,
    ) -> None:
        self._gps_monitor.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)
        self._obd_control.set_fallback_settings(stale_timeout_s=stale_timeout_s, **kwargs)


@dataclass(frozen=True, slots=True)
class SpeedSourceServices:
    observation: SpeedSourceObservationService
    admin: SpeedSourceAdminService
    control: SpeedSourceControlService


def build_speed_source_services(
    *,
    gps_monitor: GPSSpeedMonitor,
    obd_facts: ObdFacts,
    obd_projection: ObdProjection,
    obd_device_admin: ObdDeviceAdmin,
    obd_status_refresher: ObdConfiguredDeviceRefresher,
    obd_control: SpeedSourceSync,
) -> SpeedSourceServices:
    selected_source = _SelectedSourceState()
    return SpeedSourceServices(
        observation=SpeedSourceObservationService(
            gps_monitor=gps_monitor,
            obd_facts=obd_facts,
            obd_projection=obd_projection,
            selected_source=selected_source,
        ),
        admin=SpeedSourceAdminService(
            obd_device_admin=obd_device_admin,
            obd_status_refresher=obd_status_refresher,
        ),
        control=SpeedSourceControlService(
            gps_monitor=gps_monitor,
            obd_control=obd_control,
            selected_source=selected_source,
        ),
    )
