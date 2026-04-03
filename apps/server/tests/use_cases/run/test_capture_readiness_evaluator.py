from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CaptureReadinessPolicy,
    CarSnapshot,
    RunContextSnapshot,
)
from vibesensor.use_cases.run.capture_readiness_evaluator import evaluate_capture_readiness
from vibesensor.use_cases.run.capture_readiness_observation import (
    CaptureReadinessObservation,
    CaptureReadinessSensorObservation,
    CaptureReadinessSpeedObservation,
)
from vibesensor.use_cases.run.capture_readiness_state import (
    CaptureReadinessStateSnapshot,
    IntegrityState,
    SpeedObservation,
)


@dataclass(frozen=True, slots=True)
class _SpeedStatus:
    source: str = "gps"
    speed_kmh: float | None = 80.0
    age_s: float | None = 0.2
    fallback_active: bool = False


def _run_context() -> RunContextSnapshot:
    return RunContextSnapshot(
        analysis_settings=AnalysisSettingsSnapshot(
            tire_width_mm=255.0,
            tire_aspect_pct=40.0,
            rim_in=19.0,
            final_drive_ratio=3.15,
            current_gear_ratio=0.81,
        ),
        car=CarSnapshot(
            car_id="car-1",
            name="Primary",
            car_type="sedan",
            aspects={
                "tire_width_mm": 255.0,
                "tire_aspect_pct": 40.0,
                "rim_in": 19.0,
                "final_drive_ratio": 3.15,
                "current_gear_ratio": 0.81,
            },
        ),
    )


def _observation(
    *,
    speed_status: _SpeedStatus,
    active_sensors: tuple[CaptureReadinessSensorObservation, ...] = (
        CaptureReadinessSensorObservation(
            client_id="client-1",
            location_code="front_left_wheel",
            frames_dropped=0,
            queue_overflow_drops=0,
            server_queue_drops=0,
            parse_errors=0,
        ),
    ),
    now_mono: float = 108.0,
) -> CaptureReadinessObservation:
    return CaptureReadinessObservation(
        observed_at_mono_s=now_mono,
        active_sensors=active_sensors,
        run_context=_run_context(),
        speed=CaptureReadinessSpeedObservation(
            source=speed_status.source,
            speed_kmh=speed_status.speed_kmh,
            age_s=speed_status.age_s,
            fallback_active=speed_status.fallback_active,
        ),
        obd=None,
    )


def test_capture_readiness_evaluator_reports_non_live_speed_sources_explicitly() -> None:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(),
        observation=_observation(speed_status=_SpeedStatus(source="manual")),
        state=CaptureReadinessStateSnapshot(
            integrity=IntegrityState(
                active=False,
                frames_dropped=0,
                queue_overflow_drops=0,
                server_queue_drops=0,
                parse_errors=0,
                quiet_period_remaining_s=None,
            ),
            speed_history=(),
        ),
    )

    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    assert reference_check.reason_key == "speed_source_not_live"


def test_capture_readiness_evaluator_accepts_ready_observation_from_state_snapshot() -> None:
    policy = CaptureReadinessPolicy(low_sensor_count_warn_threshold=1)
    observation = _observation(speed_status=_SpeedStatus(speed_kmh=82.0))

    readiness = evaluate_capture_readiness(
        policy=policy,
        observation=observation,
        state=CaptureReadinessStateSnapshot(
            integrity=IntegrityState(
                active=False,
                frames_dropped=0,
                queue_overflow_drops=0,
                server_queue_drops=0,
                parse_errors=0,
                quiet_period_remaining_s=None,
            ),
            speed_history=(
                SpeedObservation(observed_at_mono_s=100.0, speed_kmh=81.5),
                SpeedObservation(observed_at_mono_s=104.0, speed_kmh=82.0),
                SpeedObservation(observed_at_mono_s=108.0, speed_kmh=82.0),
            ),
        ),
    )

    assert readiness.is_ready
    assert (
        next(check for check in readiness.checks if check.check_key == "capture_ready").state
        == "pass"
    )
