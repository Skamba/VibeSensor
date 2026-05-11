from __future__ import annotations

import math

import pytest
from test_support.gps import set_gps_snapshot_age

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor


@pytest.mark.parametrize(
    (
        "manual_source_selected",
        "override_mps",
        "gps_speed_mps",
        "gps_age_s",
        "connection_state",
        "stale_timeout_s",
        "expected_speed_mps",
        "expected_source",
        "expected_fallback_active",
    ),
    [
        (True, 12.0, 20.0, 0.0, "connected", None, 12.0, "manual", False),
        (True, None, 30.0, 0.0, "connected", None, 30.0, "gps", False),
        (True, None, None, None, "connected", None, None, "none", True),
        (False, 11.0, 22.0, 30.0, "connected", 5.0, 11.0, "fallback_manual", True),
    ],
    ids=[
        "default-manual-override-has-priority",
        "manual-selected-without-override-uses-fresh-gps",
        "manual-selected-without-override-and-no-gps-resolves-none",
        "stale-gps-falls-back-to-manual-override",
    ],
)
def test_resolve_speed_source_contract(
    manual_source_selected: bool,
    override_mps: float | None,
    gps_speed_mps: float | None,
    gps_age_s: float | None,
    connection_state: str,
    stale_timeout_s: float | None,
    expected_speed_mps: float | None,
    expected_source: str,
    expected_fallback_active: bool,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    assert monitor.manual_source_selected is True
    monitor.manual_source_selected = manual_source_selected
    monitor.override_speed_mps = override_mps
    monitor.speed_mps = gps_speed_mps
    monitor.connection_state = connection_state
    if gps_age_s is not None:
        set_gps_snapshot_age(monitor, age_s=gps_age_s)
    if stale_timeout_s is not None:
        monitor.stale_timeout_s = stale_timeout_s

    resolved = monitor.resolve_speed()

    assert resolved.speed_mps == expected_speed_mps
    assert resolved.source == expected_source
    assert resolved.fallback_active is expected_fallback_active


@pytest.mark.parametrize("invalid_kmh", [-1.0, math.inf, math.nan], ids=["negative", "inf", "nan"])
def test_set_speed_override_rejects_invalid_value(invalid_kmh: float) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    assert monitor.set_speed_override_kmh(invalid_kmh) is None
    assert monitor.override_speed_mps is None


def test_helper_parsers_reject_bool_and_invalid_values() -> None:
    assert GPSSpeedMonitor._read_non_negative_metric({"epx": True}, "epx") is None
    assert GPSSpeedMonitor._read_non_negative_metric({"epx": -1}, "epx") is None
    assert GPSSpeedMonitor._read_non_negative_metric({"epx": 1.5}, "epx") == 1.5

    assert GPSSpeedMonitor._tpv_mode({"mode": True}) is None
    assert GPSSpeedMonitor._tpv_mode({"mode": 3}) == 3
