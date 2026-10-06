from __future__ import annotations

from vibesensor.domain.capture_readiness import (
    CaptureReadinessCheck,
    CaptureReadinessPolicy,
)


def test_capture_readiness_check_properties_and_details_dict() -> None:
    check = CaptureReadinessCheck(
        check_key="speed_stable",
        state="fail",
        reason_key="speed_stabilizing",
        details=(("dwell_remaining_s", 2.5), ("speed_kmh", 82.0)),
    )

    assert check.failed
    assert not check.warning
    assert check.details_dict == {"dwell_remaining_s": 2.5, "speed_kmh": 82.0}


def test_capture_readiness_policy_defaults_cover_live_speed_sources() -> None:
    policy = CaptureReadinessPolicy()

    assert policy.min_ready_speed_kmh == 20.0
    assert policy.max_speed_age_s == 2.0
    assert policy.live_speed_sources == ("gps", "obd2")
