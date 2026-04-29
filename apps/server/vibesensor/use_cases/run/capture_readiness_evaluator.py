"""Pure readiness interpretation over observation and rolling state."""

from __future__ import annotations

import math

from vibesensor.domain import CaptureReadiness, CaptureReadinessCheck, CaptureReadinessPolicy
from vibesensor.shared.constants.analysis import STEADY_SPEED_RANGE_KMH, STEADY_SPEED_STDDEV_KMH
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot
from vibesensor.use_cases.run.capture_readiness_observation import (
    CaptureReadinessObservation,
    CaptureReadinessSensorObservation,
)
from vibesensor.use_cases.run.capture_readiness_state import (
    CaptureReadinessStateSnapshot,
    IntegrityState,
    SpeedObservation,
    _is_finite_number,
)

__all__ = ["evaluate_capture_readiness"]

type CaptureReadinessCheckTuple = tuple[CaptureReadinessCheck, ...]


def evaluate_capture_readiness(
    *,
    policy: CaptureReadinessPolicy,
    observation: CaptureReadinessObservation,
    state: CaptureReadinessStateSnapshot,
) -> CaptureReadiness:
    checks: CaptureReadinessCheckTuple = (
        _sensors_check(policy, observation.active_sensors, state.integrity),
        _reference_check(policy, observation),
        _speed_check(policy, observation, state.speed_history),
    )
    is_ready = not any(check.failed for check in checks)
    overall_check = _overall_check(checks, is_ready)
    return CaptureReadiness(
        is_ready=is_ready,
        checks=(*checks, overall_check),
    )


def _sensors_check(
    policy: CaptureReadinessPolicy,
    active_sensors: tuple[CaptureReadinessSensorObservation, ...],
    integrity: IntegrityState,
) -> CaptureReadinessCheck:
    live_sensor_count = len(active_sensors)
    if live_sensor_count == 0:
        return CaptureReadinessCheck(
            check_key="sensors_ready",
            state="fail",
            reason_key="no_live_sensors",
            details=(("live_sensor_count", 0),),
        )

    unassigned_count = sum(
        1 for sensor in active_sensors if not str(getattr(sensor, "location_code", "")).strip()
    )
    if unassigned_count > 0:
        return CaptureReadinessCheck(
            check_key="sensors_ready",
            state="fail",
            reason_key="sensor_locations_missing",
            details=(
                ("live_sensor_count", live_sensor_count),
                ("unassigned_sensor_count", unassigned_count),
            ),
        )

    if integrity.active:
        details: list[tuple[str, int | float | str]] = [
            ("live_sensor_count", live_sensor_count),
        ]
        for key, value in (
            ("frames_dropped", integrity.frames_dropped),
            ("queue_overflow_drops", integrity.queue_overflow_drops),
            ("server_queue_drops", integrity.server_queue_drops),
            ("parse_errors", integrity.parse_errors),
        ):
            if value > 0:
                details.append((key, value))
        if integrity.quiet_period_remaining_s is not None:
            details.append(("quiet_period_remaining_s", integrity.quiet_period_remaining_s))
        return CaptureReadinessCheck(
            check_key="sensors_ready",
            state="fail",
            reason_key="recent_integrity_events",
            details=tuple(details),
        )

    if live_sensor_count < policy.low_sensor_count_warn_threshold:
        return CaptureReadinessCheck(
            check_key="sensors_ready",
            state="warn",
            reason_key="limited_sensor_coverage",
            details=(("live_sensor_count", live_sensor_count),),
        )

    return CaptureReadinessCheck(
        check_key="sensors_ready",
        state="pass",
        reason_key="sensors_ready",
        details=(("live_sensor_count", live_sensor_count),),
    )


def _reference_check(
    policy: CaptureReadinessPolicy,
    observation: CaptureReadinessObservation,
) -> CaptureReadinessCheck:
    run_context = observation.run_context
    speed = observation.speed
    obd = observation.obd
    if not run_context.has_car_context:
        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="fail",
            reason_key="active_car_missing",
        )

    order_reference = order_reference_spec_from_snapshot(run_context.analysis_settings)
    if order_reference is None or not order_reference.is_complete:
        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="fail",
            reason_key="order_reference_incomplete",
        )

    if speed is None:
        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="fail",
            reason_key="speed_source_missing",
        )

    speed_source = speed.source
    effective_speed_kmh = speed.speed_kmh
    if speed_source == "manual":
        if (
            not _is_finite_number(effective_speed_kmh)
            or effective_speed_kmh is None
            or effective_speed_kmh <= 0.0
        ):
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="speed_sample_missing",
                details=(("speed_source", speed_source),),
            )
        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="pass",
            reason_key="reference_ready",
            details=(
                ("speed_source", speed_source),
                ("speed_kmh", round(effective_speed_kmh, 2)),
            ),
        )

    if speed.fallback_active:
        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="fail",
            reason_key="speed_source_fallback_active",
            details=(("speed_source", speed_source),),
        )

    if speed_source not in policy.live_speed_sources:
        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="fail",
            reason_key="speed_source_not_live",
            details=(("speed_source", speed_source),),
        )

    last_update_age_s = speed.age_s
    if last_update_age_s is None or last_update_age_s > policy.max_speed_age_s:
        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="fail",
            reason_key="speed_sample_stale",
            details=(
                ("speed_source", speed_source),
                ("last_update_age_s", round(last_update_age_s or 0.0, 2)),
            ),
        )

    if (
        not _is_finite_number(effective_speed_kmh)
        or effective_speed_kmh is None
        or effective_speed_kmh <= 0.0
    ):
        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="fail",
            reason_key="speed_sample_missing",
            details=(("speed_source", speed_source),),
        )

    if speed_source == "obd2":
        if order_reference is None or not order_reference.supports_engine_reference:
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="order_reference_incomplete",
                details=(("speed_source", speed_source),),
            )
        if obd is None or not _is_finite_number(obd.rpm):
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="obd_rpm_missing",
                details=(("speed_source", speed_source),),
            )
        rpm_age_s = obd.rpm_age_s
        if rpm_age_s is None or rpm_age_s > policy.max_obd_rpm_age_s:
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="obd_rpm_stale",
                details=(
                    ("speed_source", speed_source),
                    ("rpm_sample_age_s", round(rpm_age_s or 0.0, 2)),
                ),
            )

    return CaptureReadinessCheck(
        check_key="reference_ready",
        state="pass",
        reason_key="reference_ready",
        details=(
            ("speed_source", speed_source),
            ("speed_kmh", round(speed.speed_kmh or 0.0, 2)),
            ("last_update_age_s", round(last_update_age_s or 0.0, 2)),
        ),
    )


def _speed_check(
    policy: CaptureReadinessPolicy,
    observation: CaptureReadinessObservation,
    speed_history: tuple[SpeedObservation, ...],
) -> CaptureReadinessCheck:
    speed = observation.speed
    if speed is None:
        return CaptureReadinessCheck(
            check_key="speed_stable",
            state="fail",
            reason_key="speed_sample_missing",
        )

    speed_source = speed.source
    speed_kmh = speed.speed_kmh
    if speed_source == "manual":
        if not _is_finite_number(speed_kmh) or speed_kmh is None:
            return CaptureReadinessCheck(
                check_key="speed_stable",
                state="fail",
                reason_key="speed_sample_missing",
                details=(("speed_source", speed_source),),
            )
        if speed_kmh < policy.min_ready_speed_kmh:
            return CaptureReadinessCheck(
                check_key="speed_stable",
                state="fail",
                reason_key="speed_too_low",
                details=(
                    ("speed_kmh", round(speed_kmh, 2)),
                    ("minimum_speed_kmh", policy.min_ready_speed_kmh),
                ),
            )
        return CaptureReadinessCheck(
            check_key="speed_stable",
            state="pass",
            reason_key="speed_stable",
            details=(
                ("speed_kmh", round(speed_kmh, 2)),
                ("mean_speed_kmh", round(speed_kmh, 2)),
                ("range_kmh", 0.0),
                ("dwell_elapsed_s", policy.stable_speed_dwell_s),
            ),
        )

    if (
        speed_source not in policy.live_speed_sources
        or speed.fallback_active
        or speed.age_s is None
        or speed.age_s > policy.max_speed_age_s
        or not _is_finite_number(speed_kmh)
    ):
        return CaptureReadinessCheck(
            check_key="speed_stable",
            state="fail",
            reason_key="speed_sample_missing",
            details=(("speed_source", speed_source),),
        )

    assert speed_kmh is not None
    if speed_kmh < policy.min_ready_speed_kmh:
        return CaptureReadinessCheck(
            check_key="speed_stable",
            state="fail",
            reason_key="speed_too_low",
            details=(
                ("speed_kmh", round(speed_kmh, 2)),
                ("minimum_speed_kmh", policy.min_ready_speed_kmh),
            ),
        )

    if len(speed_history) < 2:
        return CaptureReadinessCheck(
            check_key="speed_stable",
            state="fail",
            reason_key="speed_stabilizing",
            details=(
                ("speed_kmh", round(speed_kmh, 2)),
                ("dwell_remaining_s", policy.stable_speed_dwell_s),
            ),
        )

    dwell_observed_s = max(
        0.0,
        observation.observed_at_mono_s - speed_history[0].observed_at_mono_s,
    )
    dwell_remaining_s = max(0.0, policy.stable_speed_dwell_s - dwell_observed_s)
    mean_speed_kmh = sum(observed.speed_kmh for observed in speed_history) / len(speed_history)
    range_kmh = max(observed.speed_kmh for observed in speed_history) - min(
        observed.speed_kmh for observed in speed_history
    )
    stddev_kmh = _stddev(tuple(observed.speed_kmh for observed in speed_history))

    if dwell_observed_s < policy.stable_speed_dwell_s:
        return CaptureReadinessCheck(
            check_key="speed_stable",
            state="fail",
            reason_key="speed_stabilizing",
            details=(
                ("speed_kmh", round(speed_kmh, 2)),
                ("dwell_remaining_s", round(dwell_remaining_s, 1)),
            ),
        )

    if range_kmh > STEADY_SPEED_RANGE_KMH or stddev_kmh > STEADY_SPEED_STDDEV_KMH:
        return CaptureReadinessCheck(
            check_key="speed_stable",
            state="fail",
            reason_key="speed_variation_high",
            details=(
                ("mean_speed_kmh", round(mean_speed_kmh, 2)),
                ("range_kmh", round(range_kmh, 2)),
                ("stddev_kmh", round(stddev_kmh, 2)),
            ),
        )

    return CaptureReadinessCheck(
        check_key="speed_stable",
        state="pass",
        reason_key="speed_stable",
        details=(
            ("speed_kmh", round(speed_kmh, 2)),
            ("mean_speed_kmh", round(mean_speed_kmh, 2)),
            ("range_kmh", round(range_kmh, 2)),
            ("dwell_elapsed_s", round(dwell_observed_s, 1)),
        ),
    )


def _overall_check(
    checks: CaptureReadinessCheckTuple,
    is_ready: bool,
) -> CaptureReadinessCheck:
    if not is_ready:
        blocking_check = next(check for check in checks if check.failed)
        return CaptureReadinessCheck(
            check_key="capture_ready",
            state="fail",
            reason_key="capture_blocked",
            details=(("blocking_check", blocking_check.check_key),),
        )
    if any(check.warning for check in checks):
        warning_check = next(check for check in checks if check.warning)
        return CaptureReadinessCheck(
            check_key="capture_ready",
            state="warn",
            reason_key="ready_with_warnings",
            details=(("warning_check", warning_check.check_key),),
        )
    return CaptureReadinessCheck(
        check_key="capture_ready",
        state="pass",
        reason_key="capture_ready",
    )


def _stddev(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(variance)
