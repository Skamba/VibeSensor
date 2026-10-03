from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.capture_readiness import CaptureReadinessPolicy
from vibesensor.domain.car import CarSnapshot
from vibesensor.domain.run_context import RunContextSnapshot
from vibesensor.recording.capture_readiness_evaluator import evaluate_capture_readiness
from vibesensor.recording.capture_readiness_observation import (
    CaptureReadinessObservation,
    CaptureReadinessSensorObservation,
    CaptureReadinessSpeedObservation,
)
from vibesensor.recording.capture_readiness_state import (
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


def test_capture_readiness_evaluator_accepts_manual_speed_source_for_start_gate() -> None:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(low_sensor_count_warn_threshold=1),
        observation=_observation(speed_status=_SpeedStatus(source="manual", speed_kmh=82.0)),
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

    assert readiness.is_ready
    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    speed_check = next(check for check in readiness.checks if check.check_key == "speed_stable")
    assert reference_check.state == "pass"
    assert reference_check.reason_key == "reference_ready"
    assert speed_check.state == "pass"
    assert speed_check.reason_key == "speed_stable"


def test_capture_readiness_evaluator_reports_non_live_speed_sources_explicitly() -> None:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(),
        observation=_observation(
            speed_status=_SpeedStatus(source="none", speed_kmh=None, age_s=None)
        ),
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


def test_capture_readiness_evaluator_blocks_manual_fallback_reference_explicitly() -> None:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(),
        observation=_observation(
            speed_status=_SpeedStatus(
                source="fallback_manual",
                speed_kmh=82.0,
                age_s=None,
                fallback_active=True,
            )
        ),
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
    assert reference_check.reason_key == "speed_source_fallback_active"


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


def _speed_check_for(
    *,
    speed_history: tuple[SpeedObservation, ...],
    age_s: float = 0.2,
) -> tuple[str, str]:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(low_sensor_count_warn_threshold=1),
        observation=_observation(
            speed_status=_SpeedStatus(speed_kmh=speed_history[-1].speed_kmh, age_s=age_s),
            now_mono=speed_history[-1].observed_at_mono_s,
        ),
        state=CaptureReadinessStateSnapshot(
            integrity=IntegrityState(
                active=False,
                frames_dropped=0,
                queue_overflow_drops=0,
                server_queue_drops=0,
                parse_errors=0,
                quiet_period_remaining_s=None,
            ),
            speed_history=speed_history,
        ),
    )
    reference = next(check for check in readiness.checks if check.check_key == "reference_ready")
    speed = next(check for check in readiness.checks if check.check_key == "speed_stable")
    return reference.reason_key, speed.reason_key


def _steady(start_s: float, end_s: float, step_s: float = 1.0) -> tuple[SpeedObservation, ...]:
    count = int((end_s - start_s) / step_s) + 1
    return tuple(
        SpeedObservation(observed_at_mono_s=start_s + i * step_s, speed_kmh=80.0)
        for i in range(count)
    )


def test_speed_must_hold_for_the_full_dwell_before_capture_is_ready() -> None:
    assert _speed_check_for(speed_history=_steady(100.0, 104.0))[1] == "speed_stabilizing"
    assert _speed_check_for(speed_history=_steady(100.0, 108.0))[1] == "speed_stable"


def test_a_single_speed_excursion_wider_than_the_steady_range_blocks_capture() -> None:
    # 29 samples at 80 km/h and one at 89 km/h: std-dev 1.6 km/h (< 2) but range 9 km/h (> 8).
    history = (*_steady(100.0, 128.0), SpeedObservation(observed_at_mono_s=129.0, speed_kmh=89.0))
    assert _speed_check_for(speed_history=history)[1] == "speed_variation_high"


def test_speed_older_than_two_seconds_is_stale() -> None:
    history = _steady(100.0, 108.0)
    assert _speed_check_for(speed_history=history, age_s=1.9)[0] == "reference_ready"
    assert _speed_check_for(speed_history=history, age_s=2.5)[0] == "speed_sample_stale"
