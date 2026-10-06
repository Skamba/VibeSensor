from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.capture_readiness import CaptureCapabilities, CaptureReadinessPolicy
from vibesensor.domain.car import CarOrderReferenceStatus, CarSnapshot
from vibesensor.domain.run_context import RunContextSnapshot
from vibesensor.recording.capture_readiness_evaluator import evaluate_capture_readiness
from vibesensor.recording.capture_readiness_observation import (
    CaptureReadinessObdObservation,
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
    live_source_selected: bool = True


_FULL_ASPECTS: dict[str, float] = {
    "tire_width_mm": 255.0,
    "tire_aspect_pct": 40.0,
    "rim_in": 19.0,
    "final_drive_ratio": 3.15,
    "current_gear_ratio": 0.81,
}
_TIRE_ONLY = {"tire_width_mm": 255.0, "tire_aspect_pct": 40.0, "rim_in": 19.0}


def _run_context(aspects: dict[str, float] = _FULL_ASPECTS) -> RunContextSnapshot:
    return RunContextSnapshot(
        analysis_settings=AnalysisSettingsSnapshot(**aspects),
        car=CarSnapshot(car_id="car-1", name="Primary", car_type="sedan", aspects=aspects),
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
    aspects: dict[str, float] = _FULL_ASPECTS,
    obd: CaptureReadinessObdObservation | None = None,
) -> CaptureReadinessObservation:
    return CaptureReadinessObservation(
        observed_at_mono_s=now_mono,
        active_sensors=active_sensors,
        run_context=_run_context(aspects),
        speed=CaptureReadinessSpeedObservation(
            source=speed_status.source,
            speed_kmh=speed_status.speed_kmh,
            age_s=speed_status.age_s,
            fallback_active=speed_status.fallback_active,
            live_source_selected=speed_status.live_source_selected,
        ),
        obd=obd,
    )


def test_capture_readiness_evaluator_accepts_manual_speed_source_for_start_gate() -> None:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(low_sensor_count_warn_threshold=1),
        observation=_observation(speed_status=_SpeedStatus(source="manual", speed_kmh=82.0)),
        state=CaptureReadinessStateSnapshot(
            integrity=IntegrityState(),
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
            speed_status=_SpeedStatus(
                source="none", speed_kmh=None, age_s=None, live_source_selected=False
            )
        ),
        state=CaptureReadinessStateSnapshot(
            integrity=IntegrityState(),
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
            integrity=IntegrityState(),
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
            integrity=IntegrityState(),
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
            integrity=IntegrityState(),
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


def test_speed_must_hold_for_the_full_dwell_before_it_counts_as_steady() -> None:
    assert _speed_check_for(speed_history=_steady(100.0, 104.0))[1] == "speed_stabilizing"
    assert _speed_check_for(speed_history=_steady(100.0, 108.0))[1] == "speed_stable"


def test_a_single_speed_excursion_wider_than_the_steady_range_is_not_steady() -> None:
    # 29 samples at 80 km/h and one at 89 km/h: std-dev 1.6 km/h (< 2) but range 9 km/h (> 8).
    history = (*_steady(100.0, 128.0), SpeedObservation(observed_at_mono_s=129.0, speed_kmh=89.0))
    assert _speed_check_for(speed_history=history)[1] == "speed_variation_high"


@pytest.mark.parametrize("speed_source", ["gps", "obd2"])
def test_a_parked_car_with_live_speed_can_start_and_gets_steady_speed_advice(
    speed_source: str,
) -> None:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(low_sensor_count_warn_threshold=1),
        observation=_observation(
            speed_status=_SpeedStatus(source=speed_source, speed_kmh=0.0),
            obd=CaptureReadinessObdObservation(rpm=800.0, rpm_age_s=0.2),
        ),
        state=_QUIET_STATE,
    )

    checks = {check.check_key: check for check in readiness.checks}
    assert readiness.is_ready
    assert checks["reference_ready"].state == "pass"
    assert (checks["speed_stable"].state, checks["speed_stable"].reason_key) == (
        "warn",
        "speed_too_low",
    )
    assert checks["capture_ready"].reason_key == "ready_with_warnings"


def test_speed_older_than_two_seconds_is_stale() -> None:
    history = _steady(100.0, 108.0)
    assert _speed_check_for(speed_history=history, age_s=1.9)[0] == "reference_ready"
    assert _speed_check_for(speed_history=history, age_s=2.5)[0] == "speed_sample_stale"


_QUIET_STATE = CaptureReadinessStateSnapshot(
    integrity=IntegrityState(),
    speed_history=(),
)


@pytest.mark.parametrize(
    ("aspects", "speed_source", "obd", "capabilities"),
    [
        pytest.param(
            _TIRE_ONLY,
            "gps",
            None,
            CaptureCapabilities(
                wheel="ok", driveline="missing_final_drive", engine="missing_ratios"
            ),
            id="tire-only",
        ),
        pytest.param(
            {**_TIRE_ONLY, "final_drive_ratio": 3.15},
            "gps",
            None,
            CaptureCapabilities(wheel="ok", driveline="ok", engine="missing_top_gear"),
            id="no-top-gear",
        ),
        pytest.param(
            {**_TIRE_ONLY, "current_gear_ratio": 0.64},
            "gps",
            None,
            CaptureCapabilities(
                wheel="ok", driveline="missing_final_drive", engine="missing_final_drive"
            ),
            id="no-final-drive",
        ),
        pytest.param(
            _FULL_ASPECTS,
            "gps",
            None,
            CaptureCapabilities(wheel="ok", driveline="ok", engine="estimated_top_gear"),
            id="full-specs",
        ),
        pytest.param(
            _FULL_ASPECTS,
            "manual",
            None,
            CaptureCapabilities(
                wheel="manual_speed", driveline="manual_speed", engine="manual_speed"
            ),
            id="typed-in-speed-tests-nothing",
        ),
        pytest.param(
            _TIRE_ONLY,
            "manual",
            None,
            CaptureCapabilities(
                wheel="manual_speed", driveline="missing_final_drive", engine="missing_ratios"
            ),
            id="typed-in-speed-names-missing-references-first",
        ),
        pytest.param(
            _TIRE_ONLY,
            "obd2",
            CaptureReadinessObdObservation(rpm=2400.0, rpm_age_s=0.3),
            CaptureCapabilities(wheel="ok", driveline="missing_final_drive", engine="measured"),
            id="obd-without-ratios",
        ),
        pytest.param(
            {},
            "gps",
            None,
            CaptureCapabilities(
                wheel="missing_tire", driveline="missing_tire", engine="missing_tire"
            ),
            id="no-tire",
        ),
    ],
)
def test_missing_references_never_block_capture_and_show_as_capabilities(
    aspects: dict[str, float],
    speed_source: str,
    obd: CaptureReadinessObdObservation | None,
    capabilities: CaptureCapabilities,
) -> None:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(low_sensor_count_warn_threshold=1),
        observation=_observation(
            speed_status=_SpeedStatus(source=speed_source, speed_kmh=82.0),
            aspects=aspects,
            obd=obd,
        ),
        state=_QUIET_STATE,
    )

    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    assert reference_check.reason_key == "reference_ready"
    assert readiness.capabilities == capabilities


@pytest.mark.parametrize(
    ("final_drive", "top_gear", "capabilities"),
    [
        pytest.param(
            "family_default",
            "official_exact",
            CaptureCapabilities(
                wheel="ok", driveline="estimated_final_drive", engine="estimated_ratios"
            ),
            id="weak-final-drive",
        ),
        pytest.param(
            "official_exact",
            "unverified",
            CaptureCapabilities(wheel="ok", driveline="ok", engine="estimated_ratios"),
            id="weak-top-gear",
        ),
        pytest.param(
            "reputable_secondary_crosschecked",
            "official_derived",
            CaptureCapabilities(wheel="ok", driveline="ok", engine="estimated_top_gear"),
            id="checked-library-values",
        ),
    ],
)
def test_weak_library_ratios_show_as_estimated_capabilities(
    final_drive: str,
    top_gear: str,
    capabilities: CaptureCapabilities,
) -> None:
    observation = _observation(speed_status=_SpeedStatus(source="gps", speed_kmh=82.0))
    car = observation.run_context.car
    assert car is not None
    run_context = RunContextSnapshot(
        analysis_settings=observation.run_context.analysis_settings,
        car=CarSnapshot(
            car_id=car.car_id,
            name=car.name,
            car_type=car.car_type,
            aspects=dict(car.aspects),
            order_reference_status=CarOrderReferenceStatus(
                selection_source_status="exact_row",
                tire_dimensions_confidence="official_exact",
                final_drive_ratio_confidence=final_drive,
                current_gear_ratio_confidence=top_gear,
            ),
        ),
    )

    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(low_sensor_count_warn_threshold=1),
        observation=replace(observation, run_context=run_context),
        state=_QUIET_STATE,
    )

    assert readiness.capabilities == capabilities


def test_obd_speed_needs_fresh_rpm_but_no_ratios() -> None:
    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(low_sensor_count_warn_threshold=1),
        observation=_observation(
            speed_status=_SpeedStatus(source="obd2", speed_kmh=82.0),
            aspects=_TIRE_ONLY,
            obd=CaptureReadinessObdObservation(rpm=2400.0, rpm_age_s=5.0),
        ),
        state=_QUIET_STATE,
    )

    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    assert reference_check.reason_key == "obd_rpm_stale"
    assert readiness.capabilities is not None
    assert readiness.capabilities.engine == "missing_ratios"


def _with_fuel_type(
    observation: CaptureReadinessObservation, fuel_type: str
) -> CaptureReadinessObservation:
    car = observation.run_context.car
    assert car is not None
    run_context = replace(observation.run_context, car=replace(car, fuel_type=fuel_type))
    return replace(observation, run_context=run_context)


@pytest.mark.parametrize(
    ("fuel_type", "speed_source", "obd", "engine"),
    [
        # An EV has no engine, so OBD-II speed need not wait for an RPM it may never report.
        pytest.param("EV", "obd2", None, "not_applicable", id="ev-obd-without-rpm"),
        pytest.param("EV", "gps", None, "not_applicable", id="ev-gps"),
        # A plug-in hybrid's engine may be off: the speed-based estimate is hedged.
        pytest.param("PHEV", "gps", None, "hybrid_estimated", id="phev-estimated"),
        pytest.param(
            "PHEV",
            "obd2",
            CaptureReadinessObdObservation(rpm=0.0, rpm_age_s=0.2),
            "measured",
            id="phev-measured",
        ),
    ],
)
def test_the_powertrain_decides_what_the_engine_check_can_do(
    fuel_type: str,
    speed_source: str,
    obd: CaptureReadinessObdObservation | None,
    engine: str,
) -> None:
    observation = _observation(
        speed_status=_SpeedStatus(source=speed_source, speed_kmh=82.0), obd=obd
    )

    readiness = evaluate_capture_readiness(
        policy=CaptureReadinessPolicy(low_sensor_count_warn_threshold=1),
        observation=_with_fuel_type(observation, fuel_type),
        state=_QUIET_STATE,
    )

    assert readiness.capabilities == CaptureCapabilities(wheel="ok", driveline="ok", engine=engine)
    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    assert reference_check.state == "pass"
