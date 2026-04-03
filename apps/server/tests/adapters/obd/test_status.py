from __future__ import annotations

from vibesensor.adapters.http.obd_status_presentation import obd_debug_hint
from vibesensor.adapters.obd.polling import ObdPollingSnapshot
from vibesensor.adapters.obd.status import ObdMonitorStatusState, build_obd_status_snapshot


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


def test_build_obd_status_snapshot_keeps_runtime_facts_and_http_hint_separate() -> None:
    status = build_obd_status_snapshot(
        ObdMonitorStatusState(
            effective_connection_state="disconnected",
            transport_connection_state="disconnected",
            configured_device_mac="00043e5a4a4d",
            configured_device_name="OBDLink MX+",
            device_mac=None,
            device_name=None,
            paired=True,
            trusted=True,
            connected=False,
            rfcomm_channel=1,
            speed_snapshot=(10.0, 90.0),
            engine_rpm=1726.0,
            engine_rpm_ts=99.0,
            obd_selected=True,
            last_error="link down",
            helper_error=None,
            reconnect_delay_s=4.0,
            polling=_polling_snapshot(),
        ),
        now_mono=100.0,
    )

    assert status.device_mac == "00043e5a4a4d"
    assert status.device_name == "OBDLink MX+"
    assert status.last_speed_kmh == 36.0
    assert status.last_sample_age_s == 10.0
    assert status.last_rpm == 1726.0
    assert status.rpm_sample_age_s == 1.0
    assert status.poll_mode is None
    assert status.backoff_active is True
    assert status.reconnect_delay_s == 4.0
    assert obd_debug_hint(status) is not None
    assert "retrying automatically" in str(obd_debug_hint(status)).lower()


def test_build_obd_status_snapshot_hides_obd_only_fields_when_not_selected() -> None:
    status = build_obd_status_snapshot(
        ObdMonitorStatusState(
            effective_connection_state="connected",
            transport_connection_state="connected",
            configured_device_mac="00043e5a4a4d",
            configured_device_name="OBDLink MX+",
            device_mac="00043e5a4a4d",
            device_name="OBDLink MX+",
            paired=True,
            trusted=True,
            connected=True,
            rfcomm_channel=1,
            speed_snapshot=(10.0, 90.0),
            engine_rpm=1726.0,
            engine_rpm_ts=99.0,
            obd_selected=False,
            last_error=None,
            helper_error=None,
            reconnect_delay_s=1.0,
            polling=_polling_snapshot(),
        ),
        now_mono=100.0,
    )

    assert status.rpm_sample_age_s is None
    assert status.rpm_target_interval_ms is None
    assert status.rpm_effective_hz is None
    assert status.request_rtt_ms is None
    assert status.poll_mode is None
    assert status.backoff_active is False
