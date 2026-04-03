"""Pure OBD runtime-fact projection helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass

from vibesensor.adapters.obd.models import ObdStatusSnapshot
from vibesensor.adapters.obd.polling import ObdPollingSnapshot
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import MPS_TO_KMH

__all__ = ["ObdMonitorStatusState", "build_obd_status_snapshot"]


@dataclass(frozen=True, slots=True)
class ObdMonitorStatusState:
    """Immutable OBD runtime/admin snapshot for outward status presentation."""

    effective_connection_state: str
    transport_connection_state: str
    configured_device_mac: str | None
    configured_device_name: str | None
    device_mac: str | None
    device_name: str | None
    paired: bool
    trusted: bool
    connected: bool
    rfcomm_channel: int | None
    speed_snapshot: tuple[float | None, float | None]
    engine_rpm: float | None
    engine_rpm_ts: float | None
    obd_selected: bool
    last_error: str | None
    helper_error: str | None
    reconnect_delay_s: float
    polling: ObdPollingSnapshot


def build_obd_status_snapshot(
    state: ObdMonitorStatusState,
    *,
    now_mono: float | None = None,
) -> ObdStatusSnapshot:
    now = time.monotonic() if now_mono is None else now_mono

    speed_mps, last_speed_ts = state.speed_snapshot
    last_speed_age_s = None if last_speed_ts is None else round(now - last_speed_ts, 2)
    last_speed_kmh = None
    if isinstance(speed_mps, NUMERIC_TYPES) and not isinstance(speed_mps, bool):
        last_speed_kmh = round(float(speed_mps) * MPS_TO_KMH, 2)

    rpm_sample_age_s = None
    if state.obd_selected and state.engine_rpm_ts is not None:
        rpm_sample_age_s = round(now - state.engine_rpm_ts, 2)

    poll_mode = (
        state.polling.poll_mode
        if state.obd_selected and state.transport_connection_state == "connected"
        else None
    )

    return ObdStatusSnapshot(
        configured_device_mac=state.configured_device_mac,
        configured_device_name=state.configured_device_name,
        connection_state=state.effective_connection_state,
        device_mac=state.device_mac or state.configured_device_mac,
        device_name=state.device_name or state.configured_device_name,
        paired=state.paired,
        trusted=state.trusted,
        connected=state.connected,
        rfcomm_channel=state.rfcomm_channel,
        last_sample_age_s=last_speed_age_s,
        last_speed_kmh=last_speed_kmh,
        last_rpm=state.engine_rpm,
        rpm_sample_age_s=rpm_sample_age_s,
        rpm_target_interval_ms=state.polling.rpm_target_interval_ms if state.obd_selected else None,
        rpm_effective_hz=state.polling.rpm_effective_hz if state.obd_selected else None,
        request_rtt_ms=state.polling.request_rtt_ms if state.obd_selected else None,
        timeout_count=state.polling.timeout_count,
        error_count=state.polling.error_count,
        poll_mode=poll_mode,
        backoff_active=state.obd_selected and state.polling.backoff_active,
        last_error=state.last_error,
        last_raw_response=state.polling.last_raw_response,
        reconnect_delay_s=(
            round(state.reconnect_delay_s, 1)
            if state.transport_connection_state == "disconnected"
            else None
        ),
        helper_error=state.helper_error,
    )
