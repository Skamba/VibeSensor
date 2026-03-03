"""Tests for GPSSpeedMonitor status_dict(), fallback logic, and set_fallback_settings()."""

from __future__ import annotations

import time

import pytest

from vibesensor.gps_speed import (
    DEFAULT_FALLBACK_MODE,
    DEFAULT_STALE_TIMEOUT_S,
    MAX_STALE_TIMEOUT_S,
    MIN_STALE_TIMEOUT_S,
    GPSSpeedMonitor,
)

# ---------------------------------------------------------------------------
# status_dict()
# ---------------------------------------------------------------------------


class TestStatusDict:
    def test_disabled_monitor_status(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=False)
        s = m.status_dict()
        assert s["gps_enabled"] is False
        assert s["connection_state"] == "disabled"
        assert s["device"] is None
        assert s["last_update_age_s"] is None
        assert s["raw_speed_kmh"] is None
        assert s["effective_speed_kmh"] is None
        assert s["last_error"] is None
        assert s["reconnect_delay_s"] is None
        assert s["fix_mode"] is None
        assert s["fix_dimension"] == "none"
        assert s["speed_confidence"] == "low"
        assert s["fallback_active"] is False
        assert s["stale_timeout_s"] == DEFAULT_STALE_TIMEOUT_S
        assert s["fallback_mode"] == DEFAULT_FALLBACK_MODE

    def test_connected_with_fresh_data(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        m.speed_mps = 10.0  # 36 km/h
        m.last_update_ts = time.monotonic()
        s = m.status_dict()
        assert s["gps_enabled"] is True
        assert s["connection_state"] == "connected"
        assert isinstance(s["last_update_age_s"], float)
        assert s["last_update_age_s"] < 2.0
        assert s["raw_speed_kmh"] == pytest.approx(36.0, abs=0.1)
        assert s["effective_speed_kmh"] == pytest.approx(36.0, abs=0.1)
        assert s["fallback_active"] is False

    def test_status_includes_fix_quality_metadata(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.last_fix_mode = 2
        m.last_epx_m = 4.2
        m.last_epy_m = 5.1
        m.last_epv_m = 8.0
        s = m.status_dict()
        assert s["fix_mode"] == 2
        assert s["fix_dimension"] == "2d"
        assert s["speed_confidence"] == "medium"
        assert s["epx_m"] == pytest.approx(4.2)
        assert s["epy_m"] == pytest.approx(5.1)
        assert s["epv_m"] == pytest.approx(8.0)

    def test_stale_detected_on_status_dict(self) -> None:
        """status_dict() transitions connection_state to stale when GPS data is old."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        m.speed_mps = 5.0
        m.last_update_ts = time.monotonic() - 999  # way older than stale timeout
        s = m.status_dict()
        assert s["connection_state"] == "stale"

    def test_disconnected_shows_reconnect_delay(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "disconnected"
        m.current_reconnect_delay = 4.0
        s = m.status_dict()
        assert s["reconnect_delay_s"] == 4.0

    def test_connected_hides_reconnect_delay(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        m.last_update_ts = time.monotonic()
        s = m.status_dict()
        assert s["reconnect_delay_s"] is None

    def test_last_error_reported(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.last_error = "Connection refused"
        s = m.status_dict()
        assert s["last_error"] == "Connection refused"

    def test_device_info_reported(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.device_info = "/dev/ttyUSB0"
        s = m.status_dict()
        assert s["device"] == "/dev/ttyUSB0"


# ---------------------------------------------------------------------------
# Fallback logic
# ---------------------------------------------------------------------------


class TestFallback:
    def test_fresh_gps_no_fallback(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        assert m.effective_speed_mps == pytest.approx(10.0)
        assert m.fallback_active is False

    def test_stale_gps_triggers_manual_fallback(self) -> None:
        """When GPS data is stale and an override_speed_mps is set,
        effective_speed_mps returns the override (since override always wins).
        When no override is set, stale GPS triggers fallback → None."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic() - 999
        # No override set → stale GPS → fallback path → None
        assert m.effective_speed_mps is None
        assert m.fallback_active is True

    def test_stale_gps_no_override_returns_none(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic() - 999
        # No override set
        assert m.effective_speed_mps is None
        assert m.fallback_active is True

    def test_disconnected_with_override_returns_override(self) -> None:
        """With manual source selected, override takes priority."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.manual_source_selected = True
        m.connection_state = "disconnected"
        m.override_speed_mps = 25.0
        assert m.effective_speed_mps == pytest.approx(25.0)
        assert m.fallback_active is False

    def test_disconnected_no_override_returns_none(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "disconnected"
        assert m.effective_speed_mps is None
        assert m.fallback_active is True

    def test_override_always_wins(self) -> None:
        """When override_speed_mps is set AND speed_source is manual, override takes priority."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.manual_source_selected = True
        m.override_speed_mps = 25.0
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        assert m.effective_speed_mps == pytest.approx(25.0)

    def test_default_override_wins_for_backward_compat(self) -> None:
        """Default state keeps legacy behavior where manual override has top priority."""
        m = GPSSpeedMonitor(gps_enabled=True)
        assert m.manual_source_selected is None
        m.override_speed_mps = 25.0
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        assert m.effective_speed_mps == pytest.approx(25.0)
        assert m.fallback_active is False

    def test_stale_timeout_respected(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.stale_timeout_s = 5.0
        m.speed_mps = 10.0
        # Just under stale threshold
        m.last_update_ts = time.monotonic() - 4.0
        assert m.effective_speed_mps == pytest.approx(10.0)
        assert m.fallback_active is False

        # Over stale threshold — no override set → fallback returns None
        m.last_update_ts = time.monotonic() - 6.0
        assert m.effective_speed_mps is None
        assert m.fallback_active is True


# ---------------------------------------------------------------------------
# set_fallback_settings()
# ---------------------------------------------------------------------------


class TestSetFallbackSettings:
    def test_default_values(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        assert m.stale_timeout_s == DEFAULT_STALE_TIMEOUT_S
        assert m.fallback_mode == DEFAULT_FALLBACK_MODE

    def test_set_stale_timeout(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(stale_timeout_s=30.0)
        assert m.stale_timeout_s == 30.0

    def test_stale_timeout_clamped_low(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(stale_timeout_s=0.5)
        assert m.stale_timeout_s == MIN_STALE_TIMEOUT_S

    def test_stale_timeout_clamped_high(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(stale_timeout_s=999.0)
        assert m.stale_timeout_s == MAX_STALE_TIMEOUT_S

    def test_set_fallback_mode(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(fallback_mode="manual")
        assert m.fallback_mode == "manual"

    def test_invalid_fallback_mode_ignored(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(fallback_mode="obd2")  # not valid yet
        assert m.fallback_mode == DEFAULT_FALLBACK_MODE

    def test_none_args_are_noop(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.stale_timeout_s = 42.0
        m.set_fallback_settings(stale_timeout_s=None, fallback_mode=None)
        assert m.stale_timeout_s == 42.0


# ---------------------------------------------------------------------------
# _is_gps_stale()
# ---------------------------------------------------------------------------


class TestIsGpsStale:
    def test_no_update_ts_is_stale(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        assert m._is_gps_stale() is True

    def test_fresh_update_not_stale(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.last_update_ts = time.monotonic()
        assert m._is_gps_stale() is False

    def test_old_update_is_stale(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.last_update_ts = time.monotonic() - m.stale_timeout_s - 1
        assert m._is_gps_stale() is True


# ---------------------------------------------------------------------------
# SpeedSourceConfig fallback fields (domain_models)
# ---------------------------------------------------------------------------


class TestSpeedSourceConfigFallback:
    def test_default_has_fallback_fields(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

        cfg = SpeedSourceConfig.default()
        assert cfg.stale_timeout_s == 10.0
        assert cfg.fallback_mode == "manual"

    def test_from_dict_camel_case(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

        cfg = SpeedSourceConfig.from_dict(
            {"speedSource": "gps", "staleTimeoutS": 30, "fallbackMode": "manual"}
        )
        assert cfg.stale_timeout_s == 30.0
        assert cfg.fallback_mode == "manual"

    def test_from_dict_clamps_timeout(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

        cfg = SpeedSourceConfig.from_dict({"staleTimeoutS": 0.1})
        assert cfg.stale_timeout_s == 3.0
        cfg = SpeedSourceConfig.from_dict({"staleTimeoutS": 999})
        assert cfg.stale_timeout_s == 120.0

    def test_from_dict_invalid_fallback_mode_defaults(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

        cfg = SpeedSourceConfig.from_dict({"fallbackMode": "obd2"})
        assert cfg.fallback_mode == "manual"

    def test_to_dict_includes_fallback_fields(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

        cfg = SpeedSourceConfig.default()
        d = cfg.to_dict()
        assert "staleTimeoutS" in d
        assert "fallbackMode" in d
        assert d["staleTimeoutS"] == 10.0
        assert d["fallbackMode"] == "manual"

    def test_apply_update_stale_timeout(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

        cfg = SpeedSourceConfig.default()
        cfg.apply_update({"staleTimeoutS": 45})
        assert cfg.stale_timeout_s == 45.0

    def test_apply_update_fallback_mode(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

        cfg = SpeedSourceConfig.default()
        cfg.apply_update({"fallbackMode": "manual"})
        assert cfg.fallback_mode == "manual"

    def test_apply_update_ignores_invalid_fallback_mode(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

        cfg = SpeedSourceConfig.default()
        cfg.apply_update({"fallbackMode": "obd2"})
        assert cfg.fallback_mode == "manual"
