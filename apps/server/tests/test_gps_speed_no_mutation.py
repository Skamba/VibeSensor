"""Tests for issue #284: effective_speed_mps and status_dict() must not mutate state.

Verifies that:
- resolve_speed() is pure (no side effects)
- effective_speed_mps property does not mutate any instance state
- status_dict() does not mutate connection_state
- fallback_active is always consistent with the speed value returned
- Multiple reads per tick yield consistent results
"""

from __future__ import annotations

import copy
import time

import pytest

from vibesensor.gps_speed import GPSSpeedMonitor, SpeedResolution

# ---------------------------------------------------------------------------
# resolve_speed() is pure
# ---------------------------------------------------------------------------


class TestResolveSpeedPure:
    """resolve_speed() must never mutate the monitor."""

    @staticmethod
    def _snapshot(m: GPSSpeedMonitor) -> dict:
        """Capture all mutable public attributes."""
        return {k: copy.deepcopy(v) for k, v in m.__dict__.items()}

    def test_fresh_gps_no_mutation(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        before = self._snapshot(m)
        m.resolve_speed()
        assert self._snapshot(m) == before

    def test_stale_gps_no_mutation(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic() - 999
        before = self._snapshot(m)
        m.resolve_speed()
        assert self._snapshot(m) == before

    def test_manual_override_no_mutation(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.manual_source_selected = True
        m.override_speed_mps = 25.0
        before = self._snapshot(m)
        m.resolve_speed()
        assert self._snapshot(m) == before

    def test_disconnected_no_mutation(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "disconnected"
        before = self._snapshot(m)
        m.resolve_speed()
        assert self._snapshot(m) == before

    def test_legacy_override_no_mutation(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.override_speed_mps = 25.0
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        before = self._snapshot(m)
        m.resolve_speed()
        assert self._snapshot(m) == before


# ---------------------------------------------------------------------------
# effective_speed_mps property does not mutate
# ---------------------------------------------------------------------------


class TestEffectiveSpeedNoMutation:
    @staticmethod
    def _snapshot(m: GPSSpeedMonitor) -> dict:
        return {k: copy.deepcopy(v) for k, v in m.__dict__.items()}

    def test_effective_speed_does_not_mutate(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        before = self._snapshot(m)
        _ = m.effective_speed_mps
        assert self._snapshot(m) == before

    def test_effective_speed_stale_does_not_mutate(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic() - 999
        before = self._snapshot(m)
        _ = m.effective_speed_mps
        assert self._snapshot(m) == before


# ---------------------------------------------------------------------------
# status_dict() does not mutate connection_state
# ---------------------------------------------------------------------------


class TestStatusDictNoMutation:
    def test_status_dict_does_not_mutate_connection_state(self) -> None:
        """Previously, status_dict() would change connection_state from
        'connected' to 'stale' as a side effect.  It must no longer do so."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        m.speed_mps = 5.0
        m.last_update_ts = time.monotonic() - 999  # stale

        s = m.status_dict()
        # The dict should report "stale" ...
        assert s["connection_state"] == "stale"
        # ... but the underlying attribute must remain unchanged.
        assert m.connection_state == "connected"

    def test_status_dict_does_not_mutate_on_fresh_data(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "connected"
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()

        s = m.status_dict()
        assert s["connection_state"] == "connected"
        assert m.connection_state == "connected"


# ---------------------------------------------------------------------------
# fallback_active consistency
# ---------------------------------------------------------------------------


class TestFallbackActiveConsistency:
    def test_fallback_active_consistent_with_speed_fresh_gps(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        r = m.resolve_speed()
        assert r.speed_mps == 10.0
        assert r.fallback_active is False
        assert r.source == "gps"
        # Property should agree
        assert m.fallback_active is False
        assert m.effective_speed_mps == 10.0

    def test_fallback_active_consistent_with_speed_stale_gps(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.manual_source_selected = False  # GPS primary, override is fallback only
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic() - 999
        m.override_speed_mps = 25.0
        r = m.resolve_speed()
        assert r.fallback_active is True
        assert r.source == "fallback_manual"
        assert r.speed_mps == 25.0
        assert m.fallback_active is True
        assert m.effective_speed_mps == 25.0

    def test_fallback_active_consistent_disconnected(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "disconnected"
        m.override_speed_mps = 25.0
        # With legacy path (manual_source_selected=None), override takes
        # priority over fallback logic.
        r = m.resolve_speed()
        assert r.speed_mps == 25.0
        assert r.fallback_active is False  # override wins, not fallback
        assert r.source == "manual"

    def test_fallback_active_consistent_disconnected_no_override(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.connection_state = "disconnected"
        r = m.resolve_speed()
        assert r.speed_mps is None
        assert r.fallback_active is True
        assert m.fallback_active is True


# ---------------------------------------------------------------------------
# Multiple reads per tick yield consistent results
# ---------------------------------------------------------------------------


class TestMultipleReadsConsistent:
    def test_repeated_reads_consistent_fresh(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        results = [m.resolve_speed() for _ in range(5)]
        assert all(r == results[0] for r in results)

    def test_repeated_reads_consistent_stale(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.manual_source_selected = False  # GPS primary, override is fallback only
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic() - 999
        m.override_speed_mps = 25.0
        results = [m.resolve_speed() for _ in range(5)]
        assert all(r == results[0] for r in results)

    def test_effective_and_fallback_agree(self) -> None:
        """Reading effective_speed_mps and fallback_active in any order must agree."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic() - 999

        # Read in different orders — all should be consistent
        speed1 = m.effective_speed_mps
        fb1 = m.fallback_active
        fb2 = m.fallback_active
        speed2 = m.effective_speed_mps

        assert speed1 == speed2
        assert fb1 == fb2


# ---------------------------------------------------------------------------
# SpeedResolution named tuple
# ---------------------------------------------------------------------------


class TestSpeedResolution:
    def test_is_named_tuple(self) -> None:
        r = SpeedResolution(10.0, False, "gps")
        assert r.speed_mps == 10.0
        assert r.fallback_active is False
        assert r.source == "gps"
        # NamedTuple is immutable
        with pytest.raises(AttributeError):
            r.speed_mps = 20.0  # type: ignore[misc]

    def test_unpacking(self) -> None:
        speed, fb, src = SpeedResolution(None, True, "none")
        assert speed is None
        assert fb is True
        assert src == "none"


# ---------------------------------------------------------------------------
# GPS state transition: fresh → stale → fresh
# ---------------------------------------------------------------------------


class TestGPSTransitions:
    def test_fresh_to_stale_to_fresh(self) -> None:
        """Transition GPS from fresh → stale → fresh.
        Verify fallback_active and source are consistent at each stage."""
        m = GPSSpeedMonitor(gps_enabled=True)
        m.manual_source_selected = False  # GPS primary, override is fallback only
        m.override_speed_mps = 25.0  # manual override for fallback
        m.connection_state = "connected"

        # Stage 1: fresh GPS
        m.speed_mps = 10.0
        m.last_update_ts = time.monotonic()
        r1 = m.resolve_speed()
        assert r1.speed_mps == 10.0
        assert r1.fallback_active is False
        assert r1.source == "gps"

        # Stage 2: GPS becomes stale (simulate by backdating last_update_ts)
        m.last_update_ts = time.monotonic() - m.stale_timeout_s - 5
        r2 = m.resolve_speed()
        assert r2.speed_mps == 25.0  # fallback to override
        assert r2.fallback_active is True
        assert r2.source == "fallback_manual"

        # Stage 3: fresh GPS data arrives
        m.speed_mps = 15.0
        m.last_update_ts = time.monotonic()
        r3 = m.resolve_speed()
        assert r3.speed_mps == 15.0
        assert r3.fallback_active is False
        assert r3.source == "gps"
