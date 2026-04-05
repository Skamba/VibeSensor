from __future__ import annotations

from vibesensor.domain import CarSnapshot
from vibesensor.use_cases.run.capture_readiness import CaptureReadinessTracker
from vibesensor.use_cases.run.capture_readiness_observation import observe_capture_readiness


def _active_car_snapshot() -> CarSnapshot:
    return CarSnapshot(
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
    )


def _run_context(mutable_fake_settings):
    from vibesensor.use_cases.run.run_context import build_run_context_snapshot

    return build_run_context_snapshot(
        analysis_settings_snapshot=mutable_fake_settings.analysis_settings_snapshot(),
        active_car_snapshot=mutable_fake_settings.active_car_snapshot(),
    )


def _observation(
    *,
    fake_registry,
    fake_gps_monitor,
    mutable_fake_settings,
    now_mono: float,
):
    return observe_capture_readiness(
        registry=fake_registry,
        run_context=_run_context(mutable_fake_settings),
        speed_provider=fake_gps_monitor,
        now_mono=now_mono,
    )


def test_capture_readiness_passes_after_stable_dwell(
    fake_registry,
    fake_gps_monitor,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    fake_gps_monitor.speed_mps = 23.0
    fake_gps_monitor.engine_rpm = 2450.0
    fake_gps_monitor.resolved_source = "obd2"

    snapshots = []
    for now_mono in (100.0, 104.0, 108.0):
        snapshots.append(
            tracker.evaluate(
                _observation(
                    fake_registry=fake_registry,
                    fake_gps_monitor=fake_gps_monitor,
                    mutable_fake_settings=mutable_fake_settings,
                    now_mono=now_mono,
                )
            )
        )

    assert not snapshots[0].is_ready
    assert snapshots[-1].is_ready
    speed_check = next(check for check in snapshots[-1].checks if check.check_key == "speed_stable")
    assert speed_check.state == "pass"
    assert speed_check.reason_key == "speed_stable"


def test_capture_readiness_fails_when_recent_integrity_issues_are_detected(
    fake_registry,
    fake_gps_monitor,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    fake_gps_monitor.speed_mps = 24.0
    fake_gps_monitor.engine_rpm = 2600.0
    fake_gps_monitor.resolved_source = "obd2"

    tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            fake_gps_monitor=fake_gps_monitor,
            mutable_fake_settings=mutable_fake_settings,
            now_mono=200.0,
        )
    )

    active_client = fake_registry.get("active")
    assert active_client is not None
    active_client.frames_dropped = 2

    blocked = tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            fake_gps_monitor=fake_gps_monitor,
            mutable_fake_settings=mutable_fake_settings,
            now_mono=204.0,
        )
    )
    sensors_check = next(check for check in blocked.checks if check.check_key == "sensors_ready")
    assert sensors_check.state == "fail"
    assert sensors_check.reason_key == "recent_integrity_events"

    recovered = tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            fake_gps_monitor=fake_gps_monitor,
            mutable_fake_settings=mutable_fake_settings,
            now_mono=215.0,
        )
    )
    sensors_check = next(check for check in recovered.checks if check.check_key == "sensors_ready")
    assert sensors_check.state == "warn"
    assert sensors_check.reason_key == "limited_sensor_coverage"


def test_capture_readiness_blocks_without_fresh_reference(
    fake_registry,
    fake_gps_monitor,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    fake_gps_monitor.speed_mps = 22.0
    fake_gps_monitor.resolved_source = "manual"

    readiness = tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            fake_gps_monitor=fake_gps_monitor,
            mutable_fake_settings=mutable_fake_settings,
            now_mono=300.0,
        )
    )

    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    assert reference_check.state == "fail"
    assert reference_check.reason_key == "speed_source_not_live"
    assert not readiness.is_ready


def test_run_recorder_status_includes_capture_readiness(
    make_logger,
    fake_registry,
    fake_gps_monitor,
    mutable_fake_settings,
) -> None:
    mutable_fake_settings.active_car = _active_car_snapshot()
    fake_gps_monitor.speed_mps = 23.0
    fake_gps_monitor.engine_rpm = 2500.0
    fake_gps_monitor.resolved_source = "obd2"
    logger = make_logger(
        registry=fake_registry,
        gps_monitor=fake_gps_monitor,
        settings_reader=mutable_fake_settings,
    )

    logger.status()
    logger.status()
    status = logger.status()

    assert status.capture_readiness is not None
    assert not status.capture_readiness.is_ready
    assert (
        next(
            check for check in status.capture_readiness.checks if check.check_key == "capture_ready"
        ).reason_key
        == "capture_blocked"
    )
