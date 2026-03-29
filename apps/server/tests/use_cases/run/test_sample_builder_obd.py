from __future__ import annotations

import pytest


def test_build_sample_records_uses_obd_speed_and_measured_engine_rpm(
    make_logger,
    fake_gps_monitor,
) -> None:
    fake_gps_monitor.speed_mps = 12.0
    fake_gps_monitor.raw_gps_speed_mps = None
    fake_gps_monitor.resolved_source = "obd2"
    fake_gps_monitor.engine_rpm = 2150.0
    fake_gps_monitor.engine_rpm_source = "obd2"

    logger = make_logger(gps_monitor=fake_gps_monitor)

    rows = logger._sample_flush.build_sample_records(
        run_id="run-obd",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert rows[0].speed_source == "obd2"
    assert rows[0].speed_kmh == pytest.approx(43.2)
    assert rows[0].gps_speed_kmh is None
    assert rows[0].engine_rpm == pytest.approx(2150.0)
    assert rows[0].engine_rpm_source == "obd2"
