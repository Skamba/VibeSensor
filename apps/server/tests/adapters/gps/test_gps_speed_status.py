"""Tests for GPSSpeedMonitor status snapshots, fallback logic, and set_fallback_settings()."""

from __future__ import annotations

import pytest
from test_support.gps import set_gps_snapshot_age

from vibesensor.adapters.gps.gps_speed import (
    DEFAULT_STALE_TIMEOUT_S,
    MAX_STALE_TIMEOUT_S,
    MIN_STALE_TIMEOUT_S,
    GPSSpeedMonitor,
)
from vibesensor.shared.types.speed_source_config import SpeedSourceConfig

# ---------------------------------------------------------------------------
# status_snapshot()
# ---------------------------------------------------------------------------


class TestStatusSnapshot:
    def test_disabled_monitor_status(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=False)
        s = m.status_snapshot()
        assert s.gps_enabled is False
        assert s.connection_state == "disabled"
        assert s.device is None
        assert s.last_update_age_s is None
        assert s.raw_speed_kmh is None
        assert s.effective_speed_kmh is None
        assert s.last_error is None
        assert s.reconnect_delay_s is None
        assert s.fix_mode is None
        assert s.fix_dimension == "none"
        assert s.speed_confidence == "low"
        assert s.fallback_active is False
        assert s.stale_timeout_s == DEFAULT_STALE_TIMEOUT_S

    def test_connected_with_fresh_data(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        m.speed_mps = 10.0  # 36 km/h
        set_gps_snapshot_age(m)
        s = m.status_snapshot()
        assert s.gps_enabled is True
        assert s.connection_state == "connected"
        assert isinstance(s.last_update_age_s, float)
        assert s.last_update_age_s < 2.0
        assert s.raw_speed_kmh == pytest.approx(36.0, abs=0.1)
        assert s.effective_speed_kmh == pytest.approx(36.0, abs=0.1)
        assert s.fallback_active is False

    def test_status_includes_fix_quality_metadata(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.last_fix_mode = 2
        m.last_epx_m = 4.2
        m.last_epy_m = 5.1
        m.last_epv_m = 8.0
        s = m.status_snapshot()
        assert s.fix_mode == 2
        assert s.fix_dimension == "2d"
        assert s.speed_confidence == "medium"
        assert s.epx_m == pytest.approx(4.2)
        assert s.epy_m == pytest.approx(5.1)
        assert s.epv_m == pytest.approx(8.0)

    def test_stale_detected_on_status_snapshot(self) -> None:
        """status_snapshot() reports stale when GPS data is old."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        m.speed_mps = 5.0
        set_gps_snapshot_age(m, age_s=999)  # way older than stale timeout
        s = m.status_snapshot()
        assert s.connection_state == "stale"

    def test_disconnected_shows_reconnect_delay(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "disconnected"
        m.current_reconnect_delay = 4.0
        s = m.status_snapshot()
        assert s.reconnect_delay_s == 4.0

    def test_connected_hides_reconnect_delay(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        set_gps_snapshot_age(m)
        s = m.status_snapshot()
        assert s.reconnect_delay_s is None

    def test_last_error_reported(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.last_error = "Connection refused"
        s = m.status_snapshot()
        assert s.last_error == "Connection refused"

    def test_device_info_reported(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.device_info = "/dev/ttyUSB0"
        s = m.status_snapshot()
        assert s.device == "/dev/ttyUSB0"


# ---------------------------------------------------------------------------
# Fallback logic
# ---------------------------------------------------------------------------


class TestFallback:
    @pytest.mark.parametrize(
        (
            "connection_state",
            "manual_source_selected",
            "gps_speed_mps",
            "gps_age_s",
            "override_mps",
            "expected_speed_mps",
            "expected_fallback_active",
        ),
        [
            ("connected", True, 10.0, 0.0, None, 10.0, False),
            ("connected", False, 10.0, 999.0, 25.0, 25.0, True),
            ("connected", True, 10.0, 999.0, None, None, True),
            ("disconnected", True, None, None, 25.0, 25.0, False),
            ("disconnected", True, None, None, None, None, True),
            ("connected", True, 10.0, 0.0, 25.0, 25.0, False),
        ],
        ids=[
            "fresh-gps-no-fallback",
            "stale-gps-uses-manual-fallback",
            "stale-gps-without-override-resolves-none",
            "manual-override-beats-disconnected-gps",
            "disconnected-gps-without-override-resolves-none",
            "default-manual-override-beats-fresh-gps",
        ],
    )
    def test_effective_speed_fallback_contract(
        self,
        connection_state: str,
        manual_source_selected: bool,
        gps_speed_mps: float | None,
        gps_age_s: float | None,
        override_mps: float | None,
        expected_speed_mps: float | None,
        expected_fallback_active: bool,
    ) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        assert m.manual_source_selected is True
        m.connection_state = connection_state
        m.manual_source_selected = manual_source_selected
        m.speed_mps = gps_speed_mps
        if gps_age_s is not None:
            set_gps_snapshot_age(m, age_s=gps_age_s)
        m.override_speed_mps = override_mps

        if expected_speed_mps is None:
            assert m.effective_speed_mps is None
        else:
            assert m.effective_speed_mps == pytest.approx(expected_speed_mps)
        assert m.fallback_active is expected_fallback_active

    def test_stale_timeout_respected(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.stale_timeout_s = 5.0
        m.speed_mps = 10.0
        # Just under stale threshold
        set_gps_snapshot_age(m, age_s=4.0)
        assert m.effective_speed_mps == pytest.approx(10.0)
        assert m.fallback_active is False

        # Over stale threshold — no override set → fallback returns None
        set_gps_snapshot_age(m, age_s=6.0)
        assert m.effective_speed_mps is None
        assert m.fallback_active is True


# ---------------------------------------------------------------------------
# set_fallback_settings()
# ---------------------------------------------------------------------------


class TestSetFallbackSettings:
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
        self,
        initial_timeout_s: float | None,
        update_timeout_s: float | None,
        expected_timeout_s: float,
    ) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        if initial_timeout_s is not None:
            m.stale_timeout_s = initial_timeout_s

        m.set_fallback_settings(stale_timeout_s=update_timeout_s)

        assert m.stale_timeout_s == expected_timeout_s


# ---------------------------------------------------------------------------
# _is_gps_stale()
# ---------------------------------------------------------------------------


class TestIsGpsStale:
    @pytest.mark.parametrize(
        ("age_s", "expected_stale"),
        [
            pytest.param(None, True, id="no-update-timestamp-is-stale"),
            pytest.param(0.0, False, id="fresh-update-is-not-stale"),
            pytest.param(DEFAULT_STALE_TIMEOUT_S + 1, True, id="old-update-is-stale"),
        ],
    )
    def test_gps_stale_contract(self, age_s: float | None, expected_stale: bool) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        if age_s is not None:
            set_gps_snapshot_age(m, age_s=age_s)

        assert m._is_gps_stale() is expected_stale


# ---------------------------------------------------------------------------
# SpeedSourceConfig fallback fields (domain_models)
# ---------------------------------------------------------------------------


class TestSpeedSourceConfigFallback:
    def test_default_has_stale_timeout(self) -> None:
        cfg = SpeedSourceConfig.default()
        assert cfg.stale_timeout_s == 10.0

    @pytest.mark.parametrize(
        ("payload", "expected_timeout_s"),
        [
            pytest.param({"speedSource": "gps", "staleTimeoutS": 30}, 30.0, id="camel-case"),
            pytest.param({"staleTimeoutS": 0.1}, 3.0, id="clamped-low"),
            pytest.param({"staleTimeoutS": 999}, 120.0, id="clamped-high"),
        ],
    )
    def test_from_dict_stale_timeout_contract(
        self,
        payload: dict[str, object],
        expected_timeout_s: float,
    ) -> None:
        cfg = SpeedSourceConfig.from_dict(payload)
        assert cfg.stale_timeout_s == expected_timeout_s

    def test_to_dict_includes_stale_timeout(self) -> None:
        cfg = SpeedSourceConfig.default()
        d = cfg.to_dict()
        assert "staleTimeoutS" in d
        assert d["staleTimeoutS"] == 10.0

    def test_apply_update_stale_timeout(self) -> None:
        cfg = SpeedSourceConfig.default()
        cfg.apply_update({"staleTimeoutS": 45})
        assert cfg.stale_timeout_s == 45.0
