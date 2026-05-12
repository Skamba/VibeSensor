"""Public GPS status and fallback contracts."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from test_support.gps import set_gps_snapshot_age

from vibesensor.adapters.gps.gps_speed import (
    DEFAULT_STALE_TIMEOUT_S,
    MAX_STALE_TIMEOUT_S,
    MIN_STALE_TIMEOUT_S,
    GPSSpeedMonitor,
)
from vibesensor.shared.types.speed_source_config import SpeedSourceConfig


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        pytest.param(
            lambda m: None,
            {
                "gps_enabled": False,
                "connection_state": "disabled",
                "raw_speed_kmh": None,
                "effective_speed_kmh": None,
                "fix_dimension": "none",
                "speed_confidence": "low",
                "speed_source": "none",
                "fallback_active": False,
                "reconnect_delay_s": None,
                "stale_timeout_s": DEFAULT_STALE_TIMEOUT_S,
            },
            id="disabled-monitor",
        ),
        pytest.param(
            lambda m: _configure_connected_fix(m),
            {
                "gps_enabled": True,
                "connection_state": "connected",
                "raw_speed_kmh": pytest.approx(36.0, abs=0.1),
                "effective_speed_kmh": pytest.approx(36.0, abs=0.1),
                "device": "/dev/ttyUSB0",
                "last_error": "transient warning",
                "epx_m": pytest.approx(4.2),
                "epy_m": pytest.approx(5.1),
                "epv_m": pytest.approx(8.0),
                "fix_dimension": "2d",
                "speed_confidence": "medium",
                "speed_source": "gps",
                "fallback_active": False,
                "reconnect_delay_s": None,
                "stale_timeout_s": DEFAULT_STALE_TIMEOUT_S,
            },
            id="connected-fresh-gps-with-fix-quality",
        ),
        pytest.param(
            lambda m: _configure_stale_fallback(m),
            {
                "gps_enabled": True,
                "connection_state": "stale",
                "raw_speed_kmh": pytest.approx(36.0, abs=0.1),
                "effective_speed_kmh": pytest.approx(90.0, abs=0.1),
                "fix_dimension": "none",
                "speed_confidence": "low",
                "speed_source": "fallback_manual",
                "fallback_active": True,
                "reconnect_delay_s": None,
                "stale_timeout_s": 5.0,
            },
            id="stale-gps-falls-back-to-manual-speed",
        ),
        pytest.param(
            lambda m: _configure_disconnected(m),
            {
                "gps_enabled": True,
                "connection_state": "disconnected",
                "raw_speed_kmh": None,
                "effective_speed_kmh": None,
                "fix_dimension": "none",
                "speed_confidence": "low",
                "speed_source": "none",
                "fallback_active": True,
                "reconnect_delay_s": 4.0,
                "stale_timeout_s": DEFAULT_STALE_TIMEOUT_S,
            },
            id="disconnected-monitor-shows-reconnect-delay",
        ),
    ],
)
def test_status_snapshot_user_visible_contract(
    setup: Callable[[GPSSpeedMonitor], None],
    expected: dict[str, object],
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=expected["gps_enabled"] is True)
    setup(monitor)

    status = monitor.status_snapshot()

    for field, value in expected.items():
        assert getattr(status, field) == value
    if status.raw_speed_kmh is not None:
        assert isinstance(status.last_update_age_s, float)


def _configure_connected_fix(monitor: GPSSpeedMonitor) -> None:
    monitor.connection_state = "connected"
    monitor.speed_mps = 10.0
    monitor.device_info = "/dev/ttyUSB0"
    monitor.last_error = "transient warning"
    monitor.last_fix_mode = 2
    monitor.last_epx_m = 4.2
    monitor.last_epy_m = 5.1
    monitor.last_epv_m = 8.0
    set_gps_snapshot_age(monitor)


def _configure_stale_fallback(monitor: GPSSpeedMonitor) -> None:
    monitor.connection_state = "connected"
    monitor.manual_source_selected = False
    monitor.override_speed_mps = 25.0
    monitor.speed_mps = 10.0
    monitor.stale_timeout_s = 5.0
    set_gps_snapshot_age(monitor, age_s=20.0)


def _configure_disconnected(monitor: GPSSpeedMonitor) -> None:
    monitor.connection_state = "disconnected"
    monitor.current_reconnect_delay = 4.0


@pytest.mark.parametrize(
    ("gps_age_s", "expected_speed_mps", "expected_fallback_active"),
    [
        pytest.param(4.0, 10.0, False, id="fresh-within-timeout"),
        pytest.param(6.0, None, True, id="stale-over-timeout"),
    ],
)
def test_stale_timeout_controls_public_speed_resolution(
    gps_age_s: float,
    expected_speed_mps: float | None,
    expected_fallback_active: bool,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.stale_timeout_s = 5.0
    monitor.speed_mps = 10.0
    set_gps_snapshot_age(monitor, age_s=gps_age_s)

    assert monitor.effective_speed_mps == expected_speed_mps
    assert monitor.fallback_active is expected_fallback_active


@pytest.mark.parametrize(
    ("initial_timeout_s", "update_timeout_s", "expected_timeout_s"),
    [
        pytest.param(None, None, DEFAULT_STALE_TIMEOUT_S, id="default-value"),
        pytest.param(None, 30.0, 30.0, id="explicit-timeout"),
        pytest.param(None, 0.5, MIN_STALE_TIMEOUT_S, id="clamped-low"),
        pytest.param(None, 999.0, MAX_STALE_TIMEOUT_S, id="clamped-high"),
        pytest.param(42.0, None, 42.0, id="none-update-is-noop"),
    ],
)
def test_stale_timeout_settings_contract(
    initial_timeout_s: float | None,
    update_timeout_s: float | None,
    expected_timeout_s: float,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    if initial_timeout_s is not None:
        monitor.stale_timeout_s = initial_timeout_s

    monitor.set_fallback_settings(stale_timeout_s=update_timeout_s)

    assert monitor.stale_timeout_s == expected_timeout_s


@pytest.mark.parametrize(
    ("payload", "expected_timeout_s"),
    [
        pytest.param({}, 10.0, id="default"),
        pytest.param({"speedSource": "gps", "staleTimeoutS": 30}, 30.0, id="camel-case"),
        pytest.param({"staleTimeoutS": 0.1}, 3.0, id="clamped-low"),
        pytest.param({"staleTimeoutS": 999}, 120.0, id="clamped-high"),
    ],
)
def test_speed_source_config_stale_timeout_contract(
    payload: dict[str, object],
    expected_timeout_s: float,
) -> None:
    cfg = SpeedSourceConfig.from_dict(payload)
    assert cfg.stale_timeout_s == expected_timeout_s

    cfg.apply_update({"staleTimeoutS": 45})
    assert cfg.to_dict()["staleTimeoutS"] == 45.0
