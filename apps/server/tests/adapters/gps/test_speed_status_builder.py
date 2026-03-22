from __future__ import annotations

import time

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.gps.speed_status import GPSSpeedStatusState, build_status_dict


def test_build_status_dict_reports_stale_fallback_without_transport_loop() -> None:
    now = time.monotonic()
    state = GPSSpeedStatusState(
        gps_enabled=True,
        connection_state="connected",
        device_info="/dev/ttyUSB0",
        last_fix_mode=2,
        last_epx_m=4.2,
        last_epy_m=5.1,
        last_epv_m=8.0,
        raw_speed_mps=10.0,
        last_update_ts=now - 20.0,
        last_error=None,
        current_reconnect_delay=4.0,
        stale_timeout_s=5.0,
    )

    status = build_status_dict(
        state,
        resolution=SpeedResolution(25.0, True, "fallback_manual"),
        effective_connection_state="stale",
        now_mono=now,
    )

    assert status["connection_state"] == "stale"
    assert status["speed_confidence"] == "medium"
    assert status["raw_speed_kmh"] == 36.0
    assert status["effective_speed_kmh"] == 90.0
    assert status["fallback_active"] is True
    assert status["speed_source"] == "fallback_manual"
    assert status["reconnect_delay_s"] is None
