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
        pytest.param(True, 12.0, 20.0, 0.0, "connected", None, 12.0, "manual", False),
        pytest.param(True, None, 30.0, 0.0, "connected", None, 30.0, "gps", False),
        pytest.param(True, 7.0, None, None, "disconnected", None, 7.0, "manual", False),
        pytest.param(True, None, None, None, "connected", None, None, "none", True),
        pytest.param(False, 11.0, 22.0, 30.0, "connected", 5.0, 11.0, "fallback_manual", True),
        pytest.param(False, None, 22.0, 30.0, "connected", 5.0, None, "none", True),
        pytest.param(True, None, None, None, "disconnected", None, None, "none", True),
    ],
    ids=[
        "default-manual-override-has-priority",
        "manual-selected-without-override-uses-fresh-gps",
        "manual-override-used-while-gps-disconnected",
        "manual-selected-without-override-and-no-gps-resolves-none",
        "stale-gps-falls-back-to-manual-override",
        "stale-gps-without-override-resolves-none",
        "disconnected-gps-without-override-resolves-none",
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


@pytest.mark.parametrize(
    ("speed_kmh", "expected_applied_kmh", "expected_override_mps"),
    [
        pytest.param(72.0, 72.0, 20.0, id="converts-kmh-to-mps"),
        pytest.param(0.0, 0.0, 0.0, id="zero-is-stationary-override"),
        pytest.param(None, None, None, id="none-clears-override"),
        pytest.param(-1.0, None, None, id="negative-rejected"),
        pytest.param(math.inf, None, None, id="inf-rejected"),
        pytest.param(math.nan, None, None, id="nan-rejected"),
    ],
)
def test_set_speed_override_kmh_contract(
    speed_kmh: float | None,
    expected_applied_kmh: float | None,
    expected_override_mps: float | None,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.set_speed_override_kmh(90.0)

    assert monitor.set_speed_override_kmh(speed_kmh) == expected_applied_kmh
    assert monitor.override_speed_mps == expected_override_mps
