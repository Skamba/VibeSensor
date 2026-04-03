from __future__ import annotations

from vibesensor.use_cases.run.capture_readiness_observation import CaptureReadinessSensorObservation
from vibesensor.use_cases.run.capture_readiness_state import (
    CaptureReadinessState,
    CaptureReadinessStateConfig,
    CaptureReadinessStateInput,
)


def _sensor(
    *,
    location_code: str = "front_left_wheel",
    frames_dropped: int = 0,
) -> CaptureReadinessSensorObservation:
    return CaptureReadinessSensorObservation(
        client_id="client-1",
        location_code=location_code,
        frames_dropped=frames_dropped,
        queue_overflow_drops=0,
        server_queue_drops=0,
        parse_errors=0,
    )


def test_capture_readiness_state_tracks_integrity_quiet_window() -> None:
    state = CaptureReadinessState(
        config=CaptureReadinessStateConfig(
            integrity_quiet_period_s=10.0,
            stable_speed_dwell_s=8.0,
        ),
    )
    client = _sensor()

    initial = state.observe(
        CaptureReadinessStateInput(
            observed_at_mono_s=100.0,
            active_sensors=(client,),
            speed_sample_kmh=None,
        )
    )
    assert not initial.integrity.active
    assert initial.integrity.quiet_period_remaining_s is None

    issue = state.observe(
        CaptureReadinessStateInput(
            observed_at_mono_s=104.0,
            active_sensors=(_sensor(frames_dropped=2),),
            speed_sample_kmh=None,
        )
    )
    assert issue.integrity.active
    assert issue.integrity.frames_dropped == 2
    assert issue.integrity.quiet_period_remaining_s == 10.0

    expired = state.observe(
        CaptureReadinessStateInput(
            observed_at_mono_s=115.0,
            active_sensors=(client,),
            speed_sample_kmh=None,
        )
    )
    assert not expired.integrity.active
    assert expired.integrity.quiet_period_remaining_s is None


def test_capture_readiness_state_clears_speed_history_when_sample_is_invalid() -> None:
    state = CaptureReadinessState(
        config=CaptureReadinessStateConfig(
            integrity_quiet_period_s=10.0,
            stable_speed_dwell_s=8.0,
        ),
    )
    client = _sensor()

    first = state.observe(
        CaptureReadinessStateInput(
            observed_at_mono_s=100.0,
            active_sensors=(client,),
            speed_sample_kmh=80.0,
        )
    )
    second = state.observe(
        CaptureReadinessStateInput(
            observed_at_mono_s=104.0,
            active_sensors=(client,),
            speed_sample_kmh=82.0,
        )
    )
    reset = state.observe(
        CaptureReadinessStateInput(
            observed_at_mono_s=108.0,
            active_sensors=(client,),
            speed_sample_kmh=None,
        )
    )

    assert len(first.speed_history) == 1
    assert len(second.speed_history) == 2
    assert reset.speed_history == ()
