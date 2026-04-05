"""HTTP presentation helpers for adapter/runtime-backed settings payloads."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from vibesensor.adapters.http.models import (
    ObdDeviceResponse,
    ObdPairResponse,
    ObdScanResponse,
    ObdStatusResponse,
    SpeedSourceStatusResponse,
)
from vibesensor.adapters.http.obd_status_presentation import obd_debug_hint

if TYPE_CHECKING:
    from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
    from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot


def speed_source_status_response(
    snapshot: SpeedSourceStatusSnapshot,
) -> SpeedSourceStatusResponse:
    """Project a live speed-source status snapshot into the HTTP response model."""

    return SpeedSourceStatusResponse(
        gps_enabled=snapshot.gps_enabled,
        connection_state=snapshot.connection_state,
        device=snapshot.device,
        fix_mode=snapshot.fix_mode,
        fix_dimension=snapshot.fix_dimension,
        speed_confidence=snapshot.speed_confidence,
        epx_m=snapshot.epx_m,
        epy_m=snapshot.epy_m,
        epv_m=snapshot.epv_m,
        last_update_age_s=snapshot.last_update_age_s,
        raw_speed_kmh=snapshot.raw_speed_kmh,
        effective_speed_kmh=snapshot.effective_speed_kmh,
        last_error=snapshot.last_error,
        reconnect_delay_s=snapshot.reconnect_delay_s,
        fallback_active=snapshot.fallback_active,
        speed_source=snapshot.speed_source,
        stale_timeout_s=snapshot.stale_timeout_s,
    )


def obd_device_response(snapshot: ObdDeviceSnapshot) -> ObdDeviceResponse:
    """Project an OBD device snapshot into the HTTP response model."""

    return ObdDeviceResponse(
        mac_address=snapshot.mac_address,
        name=snapshot.name,
        paired=snapshot.paired,
        trusted=snapshot.trusted,
        connected=snapshot.connected,
        rfcomm_channel=snapshot.rfcomm_channel,
    )


def obd_scan_response(devices: Sequence[ObdDeviceSnapshot]) -> ObdScanResponse:
    """Project discovered OBD devices into the scan response model."""

    return ObdScanResponse(devices=[obd_device_response(device) for device in devices])


def obd_pair_response(
    *,
    configured_device_mac: str,
    configured_device_name: str | None,
    snapshot: ObdDeviceSnapshot,
) -> ObdPairResponse:
    """Project pairing results into the persisted-pair response model."""

    return ObdPairResponse(
        configured_device_mac=configured_device_mac,
        configured_device_name=configured_device_name,
        paired=snapshot.paired,
        trusted=snapshot.trusted,
        connected=snapshot.connected,
        rfcomm_channel=snapshot.rfcomm_channel,
    )


def obd_status_response(snapshot: ObdStatusSnapshot) -> ObdStatusResponse:
    """Project a detailed OBD status snapshot into the HTTP response model."""

    return ObdStatusResponse(
        configured_device_mac=snapshot.configured_device_mac,
        configured_device_name=snapshot.configured_device_name,
        connection_state=snapshot.connection_state,
        device_mac=snapshot.device_mac,
        device_name=snapshot.device_name,
        paired=snapshot.paired,
        trusted=snapshot.trusted,
        connected=snapshot.connected,
        rfcomm_channel=snapshot.rfcomm_channel,
        last_sample_age_s=snapshot.last_sample_age_s,
        last_speed_kmh=snapshot.last_speed_kmh,
        last_rpm=snapshot.last_rpm,
        rpm_sample_age_s=snapshot.rpm_sample_age_s,
        rpm_target_interval_ms=snapshot.rpm_target_interval_ms,
        rpm_effective_hz=snapshot.rpm_effective_hz,
        request_rtt_ms=snapshot.request_rtt_ms,
        timeout_count=snapshot.timeout_count,
        error_count=snapshot.error_count,
        poll_mode=snapshot.poll_mode,
        backoff_active=snapshot.backoff_active,
        last_error=snapshot.last_error,
        last_raw_response=snapshot.last_raw_response,
        reconnect_delay_s=snapshot.reconnect_delay_s,
        debug_hint=obd_debug_hint(snapshot),
    )


__all__ = [
    "obd_device_response",
    "obd_pair_response",
    "obd_scan_response",
    "obd_status_response",
    "speed_source_status_response",
]
