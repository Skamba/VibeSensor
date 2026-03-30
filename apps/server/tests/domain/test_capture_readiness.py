from __future__ import annotations

from vibesensor.domain import CaptureReadiness, CaptureReadinessCheck


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


def test_capture_readiness_filters_failed_and_warning_checks() -> None:
    readiness = CaptureReadiness(
        is_ready=False,
        checks=(
            CaptureReadinessCheck(check_key="sensors_ready", state="warn"),
            CaptureReadinessCheck(check_key="reference_ready", state="pass"),
            CaptureReadinessCheck(check_key="speed_stable", state="fail"),
        ),
    )

    assert tuple(check.check_key for check in readiness.warning_checks) == ("sensors_ready",)
    assert tuple(check.check_key for check in readiness.failed_checks) == ("speed_stable",)
