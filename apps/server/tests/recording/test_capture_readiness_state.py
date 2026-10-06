from __future__ import annotations

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.capture_readiness import CaptureReadinessPolicy
from vibesensor.domain.run_context import RunContextSnapshot
from vibesensor.recording.capture_readiness_observation import (
    CaptureReadinessObservation,
    CaptureReadinessSensorObservation,
    CaptureReadinessSpeedObservation,
)
from vibesensor.recording.capture_readiness_state import (
    CaptureReadinessState,
    CaptureReadinessStateConfig,
    CaptureReadinessStateInput,
    build_capture_readiness_state_input,
)


def _sensor(
    *,
    location_code: str = "front_left_wheel",
    frames_dropped: int = 0,
    frames_received: int = 0,
) -> CaptureReadinessSensorObservation:
    return CaptureReadinessSensorObservation(
        client_id="client-1",
        location_code=location_code,
        frames_received=frames_received,
        frames_dropped=frames_dropped,
        queue_overflow_drops=0,
        server_queue_drops=0,
        parse_errors=0,
    )


def test_capture_readiness_state_sums_frame_counts_over_the_integrity_window() -> None:
    state = CaptureReadinessState(
        config=CaptureReadinessStateConfig(
            integrity_window_s=10.0,
            stable_speed_dwell_s=8.0,
        ),
    )

    def observe(at: float, *, received: int, dropped: int):
        return state.observe(
            CaptureReadinessStateInput(
                observed_at_mono_s=at,
                active_sensors=(_sensor(frames_received=received, frames_dropped=dropped),),
                speed_sample_kmh=None,
            )
        ).integrity

    assert not observe(100.0, received=1000, dropped=5).any_events
    loss = observe(104.0, received=1038, dropped=7)
    assert (loss.frames_received, loss.frames_dropped) == (38, 2)
    assert loss.loss_ratio == 0.05
    later = observe(110.0, received=1098, dropped=7)
    assert (later.frames_received, later.frames_dropped) == (98, 2)
    expired = observe(114.5, received=1143, dropped=7)
    assert (expired.frames_received, expired.frames_dropped, expired.any_events) == (
        105,
        0,
        False,
    )


def test_capture_readiness_state_clears_speed_history_when_sample_is_invalid() -> None:
    state = CaptureReadinessState(
        config=CaptureReadinessStateConfig(
            integrity_window_s=10.0,
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


def test_build_capture_readiness_state_input_filters_non_live_speed_samples() -> None:
    observation = CaptureReadinessObservation(
        observed_at_mono_s=100.0,
        active_sensors=(_sensor(),),
        run_context=RunContextSnapshot(
            analysis_settings=AnalysisSettingsSnapshot(),
            car=None,
        ),
        speed=CaptureReadinessSpeedObservation(
            source="manual",
            speed_kmh=80.0,
            age_s=0.1,
            fallback_active=False,
            live_source_selected=False,
        ),
        obd=None,
    )

    state_input = build_capture_readiness_state_input(
        policy=CaptureReadinessPolicy(),
        observation=observation,
    )

    assert state_input.speed_sample_kmh is None
