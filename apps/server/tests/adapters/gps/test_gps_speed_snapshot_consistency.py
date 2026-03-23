from __future__ import annotations

import time
from dataclasses import replace

import pytest

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor


def test_resolve_speed_captures_policy_and_transport_snapshots_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    base_transport = monitor._transport.snapshot()
    base_policy = monitor._policy.snapshot()
    transport_calls = 0
    policy_calls = 0

    def _transport_snapshot():
        nonlocal transport_calls
        transport_calls += 1
        if transport_calls == 1:
            return replace(
                base_transport,
                gps_enabled=True,
                connection_state="connected",
                speed_snapshot=(10.0, time.monotonic()),
            )
        return replace(
            base_transport,
            gps_enabled=False,
            connection_state="disabled",
            speed_snapshot=(None, None),
        )

    def _policy_snapshot():
        nonlocal policy_calls
        policy_calls += 1
        if policy_calls == 1:
            return replace(
                base_policy,
                override_speed_mps=25.0,
                manual_source_selected=True,
                stale_timeout_s=5.0,
            )
        return replace(
            base_policy,
            override_speed_mps=None,
            manual_source_selected=False,
            stale_timeout_s=120.0,
        )

    monkeypatch.setattr(monitor._transport, "snapshot", _transport_snapshot)
    monkeypatch.setattr(monitor._policy, "snapshot", _policy_snapshot)

    resolution = monitor.resolve_speed()

    assert transport_calls == 1
    assert policy_calls == 1
    assert resolution.speed_mps == 25.0
    assert resolution.source == "manual"
    assert resolution.fallback_active is False


def test_status_snapshot_captures_policy_and_transport_snapshots_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    base_transport = monitor._transport.snapshot()
    base_policy = monitor._policy.snapshot()
    transport_calls = 0
    policy_calls = 0

    def _transport_snapshot():
        nonlocal transport_calls
        transport_calls += 1
        if transport_calls == 1:
            return replace(
                base_transport,
                gps_enabled=True,
                connection_state="connected",
                speed_snapshot=(10.0, time.monotonic()),
                device_info="/dev/ttyUSB0",
                last_fix_mode=3,
                last_error="old error",
            )
        return replace(
            base_transport,
            gps_enabled=False,
            connection_state="disabled",
            speed_snapshot=(None, None),
            device_info=None,
            last_fix_mode=None,
            last_error=None,
        )

    def _policy_snapshot():
        nonlocal policy_calls
        policy_calls += 1
        if policy_calls == 1:
            return replace(
                base_policy,
                override_speed_mps=None,
                manual_source_selected=False,
                stale_timeout_s=17.0,
            )
        return replace(
            base_policy,
            override_speed_mps=25.0,
            manual_source_selected=True,
            stale_timeout_s=99.0,
        )

    monkeypatch.setattr(monitor._transport, "snapshot", _transport_snapshot)
    monkeypatch.setattr(monitor._policy, "snapshot", _policy_snapshot)

    status = monitor.status_snapshot()

    assert transport_calls == 1
    assert policy_calls == 1
    assert status.gps_enabled is True
    assert status.connection_state == "connected"
    assert status.device == "/dev/ttyUSB0"
    assert status.fix_mode == 3
    assert status.raw_speed_kmh == pytest.approx(36.0, abs=0.1)
    assert status.stale_timeout_s == pytest.approx(17.0)


def test_disabling_gps_clears_speed_snapshot_and_zero_speed_streak() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.connection_state = "connected"
    monitor.speed_mps = 10.0
    monitor._zero_speed_streak = 2

    monitor.gps_enabled = False

    assert monitor.gps_enabled is False
    assert monitor.connection_state == "disabled"
    assert monitor._speed_snapshot == (None, None)
    assert monitor._zero_speed_streak == 0
