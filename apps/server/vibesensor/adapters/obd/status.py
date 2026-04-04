"""Pure OBD status projection over raw runtime facts and explicit policy inputs."""

from __future__ import annotations

import time
from dataclasses import dataclass

from vibesensor.adapters.obd.models import ObdStatusSnapshot
from vibesensor.adapters.obd.polling import ObdPollingSnapshot
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.constants.units import MPS_TO_KMH

__all__ = ["ObdRuntimeStatusFacts", "build_obd_status_snapshot"]


@dataclass(frozen=True, slots=True)
class ObdRuntimeStatusFacts:
    """Immutable raw runtime/admin facts for outward OBD status projection."""

    transport_connection_state: str
    device_mac: str | None
    device_name: str | None
    paired: bool
    trusted: bool
    connected: bool
    rfcomm_channel: int | None
    speed_snapshot: tuple[float | None, float | None]
    engine_rpm: float | None
    engine_rpm_ts: float | None
    last_runtime_error: str | None
    helper_error: str | None
    reconnect_delay_s: float
    polling: ObdPollingSnapshot


def build_obd_status_snapshot(
    facts: ObdRuntimeStatusFacts,
    *,
    configured_device_mac: str | None,
    configured_device_name: str | None,
    effective_connection_state: str,
    obd_selected: bool,
    now_mono: float | None = None,
) -> ObdStatusSnapshot:
    now = time.monotonic() if now_mono is None else now_mono

    speed_mps, last_speed_ts = facts.speed_snapshot
    last_speed_age_s = None if last_speed_ts is None else round(now - last_speed_ts, 2)
    last_speed_kmh = None
    if isinstance(speed_mps, NUMERIC_TYPES) and not isinstance(speed_mps, bool):
        last_speed_kmh = round(float(speed_mps) * MPS_TO_KMH, 2)

    rpm_sample_age_s = None
    if obd_selected and facts.engine_rpm_ts is not None:
        rpm_sample_age_s = round(now - facts.engine_rpm_ts, 2)

    poll_mode = (
        facts.polling.poll_mode
        if obd_selected and facts.transport_connection_state == "connected"
        else None
    )

    return ObdStatusSnapshot(
        configured_device_mac=configured_device_mac,
        configured_device_name=configured_device_name,
        connection_state=effective_connection_state,
        device_mac=facts.device_mac or configured_device_mac,
        device_name=facts.device_name or configured_device_name,
        paired=facts.paired,
        trusted=facts.trusted,
        connected=facts.connected,
        rfcomm_channel=facts.rfcomm_channel,
        last_sample_age_s=last_speed_age_s,
        last_speed_kmh=last_speed_kmh,
        last_rpm=facts.engine_rpm,
        rpm_sample_age_s=rpm_sample_age_s,
        rpm_target_interval_ms=facts.polling.rpm_target_interval_ms if obd_selected else None,
        rpm_effective_hz=facts.polling.rpm_effective_hz if obd_selected else None,
        request_rtt_ms=facts.polling.request_rtt_ms if obd_selected else None,
        timeout_count=facts.polling.timeout_count,
        error_count=facts.polling.error_count,
        poll_mode=poll_mode,
        backoff_active=obd_selected and facts.polling.backoff_active,
        last_error=facts.last_runtime_error or facts.helper_error,
        last_raw_response=facts.polling.last_raw_response,
        reconnect_delay_s=(
            round(facts.reconnect_delay_s, 1)
            if facts.transport_connection_state == "disconnected"
            else None
        ),
        helper_error=facts.helper_error,
    )
