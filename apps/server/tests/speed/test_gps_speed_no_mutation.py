"""Tests for issue #284: effective_speed_mps and status snapshots must not mutate state.

Verifies that:
- resolve_speed() is pure (no side effects)
- effective_speed_mps property does not mutate any instance state
- status_snapshot() does not mutate connection_state
- fallback_active is true only while a manual fallback speed is in use
- Multiple reads per tick yield consistent results
"""

from __future__ import annotations

import copy

import pytest
from test_support.gps import set_gps_snapshot_age

from vibesensor.speed.gps_speed import GPSSpeedMonitor


def _snapshot(m: GPSSpeedMonitor) -> dict:
    """Capture all mutable public attributes."""
    return {k: copy.deepcopy(v) for k, v in m.__dict__.items()}


# ---------------------------------------------------------------------------
# resolve_speed() is pure
# ---------------------------------------------------------------------------


def _make_fresh_gps() -> GPSSpeedMonitor:
    m = GPSSpeedMonitor(gps_enabled=True)
    m.speed_mps = 10.0
    set_gps_snapshot_age(m)
    return m


def _make_stale_gps() -> GPSSpeedMonitor:
    m = GPSSpeedMonitor(gps_enabled=True)
    m.speed_mps = 10.0
    set_gps_snapshot_age(m, age_s=999)
    return m


def _make_manual_override() -> GPSSpeedMonitor:
    m = GPSSpeedMonitor(gps_enabled=True)
    m.manual_source_selected = True
    m.override_speed_mps = 25.0
    return m


def _make_disconnected() -> GPSSpeedMonitor:
    m = GPSSpeedMonitor(gps_enabled=True)
    m.connection_state = "disconnected"
    return m


def _make_override_plus_gps() -> GPSSpeedMonitor:
    m = GPSSpeedMonitor(gps_enabled=True)
    m.manual_source_selected = True
    m.override_speed_mps = 25.0
    m.speed_mps = 10.0
    set_gps_snapshot_age(m)
    return m


def _make_stale_gps_with_fallback() -> GPSSpeedMonitor:
    m = _make_stale_gps()
    m.manual_source_selected = False  # GPS primary, override is fallback only
    m.override_speed_mps = 25.0
    return m


def _make_manual_disconnected() -> GPSSpeedMonitor:
    m = _make_manual_override()
    m.connection_state = "disconnected"
    return m


_ALL_MONITOR_STATES = [
    pytest.param(_make_fresh_gps, id="fresh_gps"),
    pytest.param(_make_stale_gps, id="stale_gps"),
    pytest.param(_make_stale_gps_with_fallback, id="stale_gps_with_fallback"),
    pytest.param(_make_manual_override, id="manual_override"),
    pytest.param(_make_disconnected, id="disconnected"),
    pytest.param(_make_override_plus_gps, id="override_plus_gps"),
]


@pytest.mark.parametrize("factory", _ALL_MONITOR_STATES)
def test_speed_reads_are_pure_and_repeatable(factory) -> None:
    """resolve_speed()/effective_speed_mps never mutate and always agree."""
    m = factory()
    before = _snapshot(m)

    results = [m.resolve_speed() for _ in range(5)]
    speed_first = m.effective_speed_mps
    speed_second = m.effective_speed_mps

    assert _snapshot(m) == before
    assert all(r == results[0] for r in results)
    assert speed_first == speed_second == results[0].speed_mps


class TestStatusSnapshotNoMutation:
    @pytest.mark.parametrize(
        ("age_s", "reported_state"),
        [pytest.param(None, "connected", id="fresh"), pytest.param(999, "stale", id="stale")],
    )
    def test_status_snapshot_does_not_mutate_connection_state(
        self, age_s: float | None, reported_state: str
    ) -> None:
        """GPS status reporting used to flip connection_state to 'stale' as a side effect."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        m.speed_mps = 10.0
        if age_s is None:
            set_gps_snapshot_age(m)
        else:
            set_gps_snapshot_age(m, age_s=age_s)

        assert m.status_snapshot().connection_state == reported_state
        assert m.connection_state == "connected"


@pytest.mark.parametrize(
    ("factory", "speed_mps", "fallback_active", "source"),
    [
        pytest.param(_make_fresh_gps, 10.0, False, "gps", id="fresh_gps"),
        pytest.param(
            _make_stale_gps_with_fallback, 25.0, True, "fallback_manual", id="stale_gps_fallback"
        ),
        pytest.param(_make_manual_disconnected, 25.0, False, "manual", id="manual_wins"),
        pytest.param(_make_disconnected, None, False, "none", id="disconnected_no_override"),
    ],
)
def test_fallback_active_consistent_with_resolved_speed(
    factory, speed_mps: float | None, fallback_active: bool, source: str
) -> None:
    m = factory()
    r = m.resolve_speed()
    assert r.speed_mps == speed_mps
    assert r.fallback_active is fallback_active
    assert r.source == source
    assert m.effective_speed_mps == speed_mps


# ---------------------------------------------------------------------------
# GPS state transition: fresh → stale → fresh
# ---------------------------------------------------------------------------


class TestGPSTransitions:
    def test_fresh_to_stale_to_fresh(self) -> None:
        """Transition GPS from fresh → stale → fresh.
        Verify fallback_active and source are consistent at each stage.
        """
        m = GPSSpeedMonitor(gps_enabled=True)
        m.manual_source_selected = False  # GPS primary, override is fallback only
        m.override_speed_mps = 25.0  # manual override for fallback
        m.connection_state = "connected"

        # Stage 1: fresh GPS
        m.speed_mps = 10.0
        set_gps_snapshot_age(m)
        r1 = m.resolve_speed()
        assert r1.speed_mps == 10.0
        assert r1.fallback_active is False
        assert r1.source == "gps"

        # Stage 2: GPS becomes stale (simulate by backdating last_update_ts)
        set_gps_snapshot_age(m, age_s=m.stale_timeout_s + 5)
        r2 = m.resolve_speed()
        assert r2.speed_mps == 25.0  # fallback to override
        assert r2.fallback_active is True
        assert r2.source == "fallback_manual"

        # Stage 3: fresh GPS data arrives
        m.speed_mps = 15.0
        set_gps_snapshot_age(m)
        r3 = m.resolve_speed()
        assert r3.speed_mps == 15.0
        assert r3.fallback_active is False
        assert r3.source == "gps"
