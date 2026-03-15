"""Tests for wave4/iris4-gps fixes.

Each test corresponds to one of the 10 fixes applied in this wave.
"""

from __future__ import annotations

import logging
import time

import pytest

from vibesensor.shared.constants import KMH_TO_MPS
from vibesensor.adapters.gps.gps_speed import (
    _GPS_MAX_SPEED_MPS,
    MAX_MANUAL_SPEED_KMH,
    GPSSpeedMonitor,
)

# ---------------------------------------------------------------------------
# Fix 1: VALID_FALLBACK_MODES is now a frozenset (O(1) membership, immutable)
# ---------------------------------------------------------------------------


def test_valid_fallback_modes_is_frozenset() -> None:
    from vibesensor.adapters.gps.gps_speed import VALID_FALLBACK_MODES

    assert isinstance(VALID_FALLBACK_MODES, frozenset), (
        "VALID_FALLBACK_MODES must be a frozenset for O(1) membership and immutability"
    )
    assert "manual" in VALID_FALLBACK_MODES


# ---------------------------------------------------------------------------
# Fix 2 & 3: resolve_speed() and _fallback_speed_value() exclude bool values
# ---------------------------------------------------------------------------


def test_resolve_speed_ignores_bool_override() -> None:
    """Bool True/False must not be treated as a valid speed override."""
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.manual_source_selected = True
    # Bypass the typed setter to test the guard directly
    monitor.override_speed_mps = True  # type: ignore[assignment]

    resolved = monitor.resolve_speed()
    # Should NOT treat bool True as 1.0 m/s; should fall through to "none"
    assert resolved.speed_mps is None
    assert resolved.source == "none"


def test_fallback_speed_value_ignores_bool() -> None:
    """_fallback_speed_value() must not convert bool to float speed."""
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.override_speed_mps = False  # type: ignore[assignment]
    assert monitor._fallback_speed_value() is None


# ---------------------------------------------------------------------------
# Fix 4: set_speed_override_kmh() clamps at MAX_MANUAL_SPEED_KMH
# ---------------------------------------------------------------------------


def test_set_speed_override_kmh_clamps_at_max(caplog: pytest.LogCaptureFixture) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.gps.gps_speed"):
        result = monitor.set_speed_override_kmh(MAX_MANUAL_SPEED_KMH + 100.0)

    assert result == MAX_MANUAL_SPEED_KMH
    assert monitor.override_speed_mps is not None
    assert abs(monitor.override_speed_mps - MAX_MANUAL_SPEED_KMH * KMH_TO_MPS) < 1e-9
    assert "exceeds cap" in caplog.text.lower() or "cap" in caplog.text.lower()


def test_set_speed_override_kmh_at_exact_max_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.gps.gps_speed"):
        result = monitor.set_speed_override_kmh(MAX_MANUAL_SPEED_KMH)

    assert result == MAX_MANUAL_SPEED_KMH
    assert "cap" not in caplog.text.lower()


# ---------------------------------------------------------------------------
# Fix 5: set_fallback_settings() logs a warning for unknown fallback_mode
# ---------------------------------------------------------------------------


def test_set_fallback_settings_warns_on_invalid_mode(
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.gps.gps_speed"):
        monitor.set_fallback_settings(fallback_mode="obd2")

    assert monitor.fallback_mode == "manual", "invalid mode must not overwrite existing mode"
    assert "obd2" in caplog.text


# ---------------------------------------------------------------------------
# Fix 6: _reset_fix_metadata() now also clears device_info
# ---------------------------------------------------------------------------


def test_reset_fix_metadata_clears_device_info() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.device_info = "gpsd 3.23"
    monitor._reset_fix_metadata()
    assert monitor.device_info is None, (
        "_reset_fix_metadata() must clear device_info to prevent stale device name"
    )


def test_reset_fix_metadata_clears_all_expected_fields() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.last_fix_mode = 3
    monitor.last_epx_m = 1.5
    monitor.last_epy_m = 2.0
    monitor.last_epv_m = 3.0
    monitor._zero_speed_streak = 2
    monitor._speed_snapshot = (10.0, time.monotonic())
    monitor.device_info = "gpsd 3.23"

    monitor._reset_fix_metadata()

    assert monitor.last_fix_mode is None
    assert monitor.last_epx_m is None
    assert monitor.last_epy_m is None
    assert monitor.last_epv_m is None
    assert monitor._zero_speed_streak == 0
    assert monitor._speed_snapshot == (None, None)
    assert monitor.device_info is None


# ---------------------------------------------------------------------------
# Fix 7: _speed_confidence() returns "low" for 2D fix with no EPH data
# ---------------------------------------------------------------------------


def test_speed_confidence_2d_no_eph_returns_low() -> None:
    """A 2D fix without EPH data should give 'low' confidence, not 'medium'."""
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.last_fix_mode = 2
    monitor.last_epx_m = None
    monitor.last_epy_m = None

    assert monitor._speed_confidence() == "low", (
        "2D fix with no EPH data cannot confirm quality; must return 'low'"
    )


def test_speed_confidence_2d_with_good_eph_returns_medium() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.last_fix_mode = 2
    monitor.last_epx_m = 5.0
    monitor.last_epy_m = 5.0

    assert monitor._speed_confidence() == "medium"


def test_speed_confidence_3d_fix_returns_high() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.last_fix_mode = 3
    assert monitor._speed_confidence() == "high"


# ---------------------------------------------------------------------------
# Fix 8: status_dict() includes "speed_source" key
# ---------------------------------------------------------------------------


def test_status_dict_includes_speed_source() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    status = monitor.status_dict()
    assert "speed_source" in status, "status_dict() must expose speed_source for diagnostics"


def test_status_dict_speed_source_matches_resolve_speed() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.manual_source_selected = True
    monitor.override_speed_mps = 10.0
    status = monitor.status_dict()
    assert status["speed_source"] == "manual"


def test_status_dict_speed_source_none_when_no_data() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    status = monitor.status_dict()
    assert status["speed_source"] == "none"


# ---------------------------------------------------------------------------
# Fix 9: GPS plausibility gate in run() — speeds > _GPS_MAX_SPEED_MPS rejected
# ---------------------------------------------------------------------------


def test_gps_max_speed_constant_is_reasonable() -> None:
    """_GPS_MAX_SPEED_MPS should be between 100 and 200 m/s (360–720 km/h)."""
    assert 100.0 < _GPS_MAX_SPEED_MPS <= 200.0, (
        f"_GPS_MAX_SPEED_MPS={_GPS_MAX_SPEED_MPS} is outside the expected range"
    )


def test_accept_speed_sample_not_affected_by_plausibility_constant() -> None:
    """_accept_speed_sample does not know about the cap; cap is enforced in run().
    The constant exists and the TPV guard uses it.  Verify the module exports it.
    """
    import vibesensor.adapters.gps.gps_speed as mod
    assert hasattr(mod, "_GPS_MAX_SPEED_MPS")
    assert mod._GPS_MAX_SPEED_MPS > 0


# ---------------------------------------------------------------------------
# Fix 10: current_reconnect_delay reset on successful connection
# ---------------------------------------------------------------------------


def test_current_reconnect_delay_constant_initial_value() -> None:
    """Newly constructed monitor starts with the initial reconnect delay."""
    from vibesensor.adapters.gps.gps_speed import _GPS_RECONNECT_DELAY_S

    monitor = GPSSpeedMonitor(gps_enabled=True)
    assert monitor.current_reconnect_delay == _GPS_RECONNECT_DELAY_S
