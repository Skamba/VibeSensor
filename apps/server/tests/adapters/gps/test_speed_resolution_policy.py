from __future__ import annotations

from vibesensor.adapters.gps.speed_resolution import (
    MAX_STALE_TIMEOUT_S,
    MIN_STALE_TIMEOUT_S,
    SpeedResolutionPolicy,
)


def test_policy_resolves_stale_gps_to_manual_fallback() -> None:
    policy = SpeedResolutionPolicy(
        override_speed_mps=25.0,
        manual_source_selected=False,
        stale_timeout_s=5.0,
        monotonic=lambda: 100.0,
    )

    resolution = policy.resolve(
        gps_enabled=True,
        connection_state="connected",
        speed_snapshot=(10.0, 90.0),
    )

    assert resolution.speed_mps == 25.0
    assert resolution.fallback_active is True
    assert resolution.source == "fallback_manual"


def test_policy_clamps_stale_timeout_without_transport_state() -> None:
    policy = SpeedResolutionPolicy()

    policy.set_fallback_settings(stale_timeout_s=0.5)
    assert policy.stale_timeout_s == MIN_STALE_TIMEOUT_S

    policy.set_fallback_settings(stale_timeout_s=999.0)
    assert policy.stale_timeout_s == MAX_STALE_TIMEOUT_S
