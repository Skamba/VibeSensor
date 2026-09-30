from __future__ import annotations

from vibesensor.adapters.http.obd_status_presentation import obd_debug_hint
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.polling import (
    ObdPidPollResult,
    ObdPollingCadence,
    ObdPollingSnapshot,
    ObdPollResult,
)
from vibesensor.adapters.obd.runtime_state import ObdRuntimeState


def _polling_snapshot(*, backoff_active: bool = True) -> ObdPollingSnapshot:
    return ObdPollingSnapshot(
        rpm_target_interval_ms=75,
        rpm_effective_hz=20.0,
        request_rtt_ms=140.0,
        timeout_count=1,
        error_count=0,
        poll_mode="rpm_only_backoff",
        backoff_active=backoff_active,
        last_raw_response="410C1AF8",
    )


def _state_with_samples(*, device_name: str | None) -> ObdRuntimeState:
    """Runtime state with a 1726 rpm sample at t=99s and a 10 m/s speed at t=90s."""

    state = ObdRuntimeState(initial_reconnect_delay_s=1.0, engine_rpm_stale_timeout_s=2.0)
    state.apply_poll_result(
        ObdPollResult(
            rpm=ObdPidPollResult(
                value=1726.0,
                raw_response="410C1AF8",
                error=None,
                duration_s=0.0,
                executed=True,
                started_at_s=99.0,
            ),
            speed=ObdPidPollResult.skipped(),
        ),
        now=99.0,
        polling=ObdPollingCadence(max_interval_s=0.75),
    )
    state.speed_snapshot = (10.0, 90.0)
    state.apply_device_snapshot(
        ObdDeviceSnapshot(
            mac_address="02000000004d",
            name=device_name,
            paired=True,
            trusted=True,
            connected=True,
            rfcomm_channel=1,
        ),
    )
    return state


def test_status_snapshot_keeps_runtime_facts_and_http_hint_separate() -> None:
    state = _state_with_samples(device_name=None)
    state.set_connection_state("disconnected", error="link down", reconnect_delay_s=4.0)

    status = state.status_snapshot(
        polling=_polling_snapshot(),
        configured_device_mac="02000000004d",
        configured_device_name="OBDLink MX+",
        effective_connection_state="disconnected",
        obd_selected=True,
        now_mono=100.0,
    )

    assert status.device_mac == "02000000004d"
    assert status.device_name == "OBDLink MX+"
    assert status.connected is False
    assert status.last_speed_kmh == 36.0
    assert status.last_sample_age_s == 10.0
    assert status.last_rpm == 1726.0
    assert status.rpm_sample_age_s == 1.0
    assert status.poll_mode is None
    assert status.backoff_active is True
    assert status.reconnect_delay_s == 4.0
    assert status.last_error == "link down"
    assert obd_debug_hint(status) is not None
    assert "retrying automatically" in str(obd_debug_hint(status)).lower()


def test_status_snapshot_hides_obd_only_fields_when_not_selected() -> None:
    state = _state_with_samples(device_name="OBDLink MX+")
    state.set_connection_state("connected", error=None)

    status = state.status_snapshot(
        polling=_polling_snapshot(),
        configured_device_mac="02000000004d",
        configured_device_name="OBDLink MX+",
        effective_connection_state="connected",
        obd_selected=False,
        now_mono=100.0,
    )

    assert status.last_rpm == 1726.0
    assert status.rpm_sample_age_s is None
    assert status.rpm_target_interval_ms is None
    assert status.rpm_effective_hz is None
    assert status.request_rtt_ms is None
    assert status.poll_mode is None
    assert status.backoff_active is False
    assert status.reconnect_delay_s is None


def test_status_snapshot_reports_poll_mode_only_while_connected_and_selected() -> None:
    state = _state_with_samples(device_name="OBDLink MX+")
    state.set_connection_state("connected", error=None)

    status = state.status_snapshot(
        polling=_polling_snapshot(),
        configured_device_mac="02000000004d",
        configured_device_name="OBDLink MX+",
        effective_connection_state="connected",
        obd_selected=True,
        now_mono=100.0,
    )

    assert status.poll_mode == "rpm_only_backoff"
    assert status.rpm_target_interval_ms == 75
    assert status.timeout_count == 1
    assert status.last_raw_response == "410C1AF8"
