from __future__ import annotations

from vibesensor.domain.car import CarSnapshot
from vibesensor.recording.capture_readiness import CaptureReadinessTracker
from vibesensor.recording.capture_readiness_observation import observe_capture_readiness
from vibesensor.settings.services import build_settings_services


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
    from vibesensor.recording.run_context import build_run_context_snapshot

    return build_run_context_snapshot(
        analysis_settings_snapshot=mutable_fake_settings.analysis_settings_snapshot(),
        active_car_snapshot=mutable_fake_settings.active_car_snapshot(),
    )


def _observation(
    *,
    fake_registry,
    speed_rig,
    mutable_fake_settings,
    sensor_metadata_reader=None,
    now_mono: float,
):
    return observe_capture_readiness(
        registry=fake_registry,
        run_context=_run_context(mutable_fake_settings),
        speed_provider=speed_rig.observation,
        sensor_metadata_reader=sensor_metadata_reader,
        now_mono=now_mono,
    )


def test_steady_speed_is_advice_that_passes_after_the_dwell(
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    speed_rig.obd_reading(speed_kmh=82.8, rpm=2450.0)

    snapshots = []
    for now_mono in (100.0, 104.0, 108.0):
        snapshots.append(
            tracker.evaluate(
                _observation(
                    fake_registry=fake_registry,
                    speed_rig=speed_rig,
                    mutable_fake_settings=mutable_fake_settings,
                    now_mono=now_mono,
                )
            )
        )

    # Start is allowed at once; the dwell only turns the advice into a pass.
    assert all(snapshot.is_ready for snapshot in snapshots)
    first = next(check for check in snapshots[0].checks if check.check_key == "speed_stable")
    assert (first.state, first.reason_key) == ("warn", "speed_stabilizing")
    speed_check = next(check for check in snapshots[-1].checks if check.check_key == "speed_stable")
    assert speed_check.state == "pass"
    assert speed_check.reason_key == "speed_stable"


def test_capture_readiness_accepts_manual_speed_source_for_start_gate(
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    speed_rig.manual(79.2)

    readiness = tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            speed_rig=speed_rig,
            mutable_fake_settings=mutable_fake_settings,
            now_mono=150.0,
        )
    )

    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    speed_check = next(check for check in readiness.checks if check.check_key == "speed_stable")
    assert readiness.is_ready
    assert reference_check.state == "pass"
    assert reference_check.reason_key == "reference_ready"
    assert speed_check.state == "pass"
    assert speed_check.reason_key == "speed_stable"


def test_capture_readiness_uses_persisted_sensor_location_metadata_when_runtime_location_is_blank(
    single_sensor_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    speed_rig.obd_reading(speed_kmh=82.8, rpm=2450.0)

    sensor_id = "001122334455"
    fake_registry = single_sensor_registry(sensor_id)
    sensor_metadata_reader = build_settings_services().sensor_settings
    sensor_metadata_reader.assign_sensor_location(sensor_id, "front_left_wheel")

    snapshots = []
    for now_mono in (100.0, 104.0, 108.0):
        snapshots.append(
            tracker.evaluate(
                _observation(
                    fake_registry=fake_registry,
                    speed_rig=speed_rig,
                    mutable_fake_settings=mutable_fake_settings,
                    sensor_metadata_reader=sensor_metadata_reader,
                    now_mono=now_mono,
                )
            )
        )

    sensors_check = next(
        check for check in snapshots[-1].checks if check.check_key == "sensors_ready"
    )
    assert sensors_check.state == "warn"
    assert sensors_check.reason_key == "limited_sensor_coverage"
    assert snapshots[-1].is_ready


def _sensors_check(readiness):
    return next(check for check in readiness.checks if check.check_key == "sensors_ready")


def test_frame_loss_blocks_start_only_above_two_percent_over_ten_seconds(
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    # A sensor sends 10 frames a second. One lost frame warns; Start waits only
    # while more than 2 % of the last 10 s of frames went missing.
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    speed_rig.obd_reading(speed_kmh=86.4, rpm=2600.0)
    observe = {
        "fake_registry": fake_registry,
        "speed_rig": speed_rig,
        "mutable_fake_settings": mutable_fake_settings,
    }
    active_client = fake_registry.get("active")
    assert active_client is not None
    tracker.evaluate(_observation(**observe, now_mono=200.0))

    active_client.frames_total = 99
    active_client.frames_dropped = 1
    one_lost = tracker.evaluate(_observation(**observe, now_mono=210.0))
    assert one_lost.is_ready
    check = _sensors_check(one_lost)
    assert (check.state, check.reason_key) == ("warn", "recent_frame_loss")
    assert ("frame_loss_pct", 1.0) in check.details

    active_client.frames_total = 197
    active_client.frames_dropped = 3
    two_percent = tracker.evaluate(_observation(**observe, now_mono=219.0))
    assert two_percent.is_ready
    assert _sensors_check(two_percent).reason_key == "recent_frame_loss"

    active_client.frames_total = 217
    active_client.frames_dropped = 6
    burst = tracker.evaluate(_observation(**observe, now_mono=221.0))
    assert not burst.is_ready
    check = _sensors_check(burst)
    assert (check.state, check.reason_key) == ("fail", "frame_loss_high")
    assert ("frames_dropped", 5) in check.details

    # The burst leaves the 10 s window: Start is available again.
    active_client.frames_total = 337
    recovered = tracker.evaluate(_observation(**observe, now_mono=233.0))
    assert recovered.is_ready
    assert _sensors_check(recovered).reason_key == "limited_sensor_coverage"


def test_capture_readiness_ignores_frames_lost_to_an_expected_interruption(
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    # A Bluetooth OBD scan starves the shared radio: the loss it causes is
    # expected and must not hold the dashboard at "Preparing".
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    speed_rig.obd_reading(speed_kmh=86.4, rpm=2600.0)
    observe = {
        "fake_registry": fake_registry,
        "speed_rig": speed_rig,
        "mutable_fake_settings": mutable_fake_settings,
    }
    tracker.evaluate(_observation(**observe, now_mono=200.0))
    active_client = fake_registry.get("active")
    assert active_client is not None
    active_client.frames_total = 20
    active_client.frames_dropped = 14
    active_client.expected_frames_dropped = 13

    one_real_loss = tracker.evaluate(_observation(**observe, now_mono=204.0))
    assert one_real_loss.is_ready is False
    sensors_check = _sensors_check(one_real_loss)
    assert sensors_check.reason_key == "frame_loss_high"
    assert ("frames_dropped", 1) in sensors_check.details

    active_client.frames_total = 140
    active_client.frames_dropped = 40
    active_client.expected_frames_dropped = 39
    after_window = tracker.evaluate(_observation(**observe, now_mono=216.0))
    assert _sensors_check(after_window).reason_key == "limited_sensor_coverage"


def test_capture_readiness_blocks_while_a_sensor_timing_is_unreliable(
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    # A sensor stamping behind real time would record rows analysis skips:
    # block the start instead of recording a run that ends empty.
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    speed_rig.obd_reading(speed_kmh=86.4, rpm=2600.0)
    active_client = fake_registry.get("active")
    assert active_client is not None
    active_client.timing_guard.state = "timestamp_lag"

    blocked = tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            speed_rig=speed_rig,
            mutable_fake_settings=mutable_fake_settings,
            now_mono=200.0,
        )
    )

    sensors_check = next(check for check in blocked.checks if check.check_key == "sensors_ready")
    assert sensors_check.state == "fail"
    assert sensors_check.reason_key == "sensor_timing_unreliable"
    assert dict(sensors_check.details)["timing_unreliable_sensor_count"] == 1
    assert not blocked.is_ready


def test_capture_readiness_blocks_without_resolved_speed_source(
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    # GPS disabled in the config and no manual speed: nothing resolves a speed.
    speed_rig.gps.gps_enabled = False

    readiness = tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            speed_rig=speed_rig,
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


def test_capture_readiness_blocks_when_manual_fallback_is_active(
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    speed_rig.manual_fallback(79.2)

    readiness = tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            speed_rig=speed_rig,
            mutable_fake_settings=mutable_fake_settings,
            now_mono=320.0,
        )
    )

    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    assert reference_check.state == "fail"
    assert reference_check.reason_key == "speed_source_fallback_active"
    assert not readiness.is_ready


def test_gps_without_fix_or_manual_speed_waits_for_a_reading_without_claiming_fallback(
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    tracker = CaptureReadinessTracker()
    mutable_fake_settings.active_car = _active_car_snapshot()
    # GPS selected and enabled but it has no fix; no manual speed is configured.
    speed_rig.services.control.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        selected_source="gps",
    )
    speed_rig.gps_speed(None)

    status = speed_rig.observation.status_snapshot()
    readiness = tracker.evaluate(
        _observation(
            fake_registry=fake_registry,
            speed_rig=speed_rig,
            mutable_fake_settings=mutable_fake_settings,
            now_mono=330.0,
        )
    )

    assert status.fallback_active is False
    assert status.speed_source == "none"
    assert status.effective_speed_kmh is None
    reference_check = next(
        check for check in readiness.checks if check.check_key == "reference_ready"
    )
    assert reference_check.state == "fail"
    assert reference_check.reason_key == "speed_sample_missing"
    assert not readiness.is_ready


def test_run_recorder_status_includes_capture_readiness(
    make_logger,
    fake_registry,
    speed_rig,
    mutable_fake_settings,
) -> None:
    mutable_fake_settings.active_car = _active_car_snapshot()
    speed_rig.obd_reading(speed_kmh=82.8, rpm=2500.0)
    logger = make_logger(
        registry=fake_registry,
        gps_monitor=speed_rig.observation,
        settings_reader=mutable_fake_settings,
    )

    logger.status()
    logger.status()
    status = logger.status()

    assert status.capture_readiness is not None
    assert status.capture_readiness.is_ready
    assert (
        next(
            check for check in status.capture_readiness.checks if check.check_key == "capture_ready"
        ).reason_key
        == "ready_with_warnings"
    )
