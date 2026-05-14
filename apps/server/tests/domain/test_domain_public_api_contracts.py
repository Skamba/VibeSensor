"""Focused public API and settings-to-domain contract tests."""

from __future__ import annotations

import pytest
from test_support.settings_services import build_settings_services

import vibesensor.domain as domain
from vibesensor.domain import (
    Car,
    DrivingPhase,
    Finding,
    Run,
    RunCapture,
    RunStatus,
    Sensor,
    SensorPlacement,
    SpeedSource,
    SuitabilityCheck,
    speed_bin_label,
    transition_run,
)


def test_domain_facade_all_exports_are_importable() -> None:
    missing = [name for name in domain.__all__ if not hasattr(domain, name)]
    assert not missing


def test_public_domain_imports_support_run_ready_configuration() -> None:
    car = Car(
        name="Track Car",
        car_type="hatchback",
        aspects={
            "tire_width_mm": 245.0,
            "tire_aspect_pct": 40.0,
            "rim_in": 18.0,
            "final_drive_ratio": 3.23,
        },
    )
    sensor = Sensor(
        sensor_id="aabbccddeeff",
        placement=SensorPlacement.from_code("front_left_wheel"),
    )
    speed_source = SpeedSource(kind="manual", manual_speed_kmh=82.0)
    run = Run()

    run.start()

    assert isinstance(car, Car)
    assert isinstance(sensor.placement, SensorPlacement)
    assert isinstance(speed_source, SpeedSource)
    assert DrivingPhase.CRUISE.value == "cruise"
    assert run.is_recording
    assert RunCapture(run_id="run-ready").run_id == "run-ready"
    assert Finding(finding_id="F001").finding_id == "F001"
    assert SuitabilityCheck("SUITABILITY_CHECK_SPEED_VARIATION", "pass").passed is True
    assert transition_run(None, RunStatus.RECORDING) is RunStatus.RECORDING
    assert speed_bin_label(83.0) == "80-90 km/h"


def test_default_car_profile_becomes_analysis_ready_after_selection() -> None:
    services = build_settings_services()

    created = services.car_settings.add_car({})
    car_id = created.cars[0]["id"]
    services.car_settings.set_active_car(car_id)

    active_car = services.car_settings.active_car()
    active_snapshot = services.car_settings.active_car_snapshot()
    active_aspects = services.car_settings.active_car_aspects()

    assert active_car is not None
    assert active_car.display_name == "Unnamed Car (sedan)"
    assert active_car.tire_circumference_m is not None
    assert active_snapshot is not None
    assert active_snapshot.car_id == car_id
    assert active_snapshot.name == "Unnamed Car"
    assert active_snapshot.car_type == "sedan"
    assert active_aspects is not None
    assert active_aspects["tire_width_mm"] > 0
    assert active_aspects["tire_aspect_pct"] > 0
    assert active_aspects["rim_in"] > 0


def test_settings_service_mutations_derive_updated_domain_objects() -> None:
    services = build_settings_services()

    created = services.car_settings.add_car(
        {
            "name": "Daily Driver",
            "type": "wagon",
            "aspects": {
                "tire_width_mm": 225.0,
                "tire_aspect_pct": 45.0,
                "rim_in": 17.0,
                "final_drive_ratio": 3.08,
            },
        }
    )
    car_id = created.cars[0]["id"]
    services.car_settings.set_active_car(car_id)
    services.sensor_settings.assign_sensor_location("AA:BB:CC:DD:EE:FF", "front_left_wheel")
    services.speed_source_settings.update_speed_source(
        {"speedSource": "manual", "manualSpeedKph": 62.0}
    )

    active_car = services.car_settings.active_car()
    active_snapshot = services.car_settings.active_car_snapshot()
    derived_sensors = services.sensor_settings.sensors()
    speed_source = services.speed_source_settings.speed_source_config().to_speed_source()

    assert active_car is not None
    assert active_car.display_name == "Daily Driver (wagon)"
    assert active_car.tire_width_mm == pytest.approx(225.0)
    assert active_car.tire_circumference_m is not None
    assert active_snapshot is not None
    assert active_snapshot.car_id == car_id
    assert active_snapshot.car_type == "wagon"
    assert derived_sensors[0].sensor_id == "aabbccddeeff"
    assert derived_sensors[0].display_name == "Front Left Wheel"
    assert derived_sensors[0].placement is not None
    assert derived_sensors[0].placement.display_name == "Front Left Wheel"
    assert speed_source.label == "Manual"
    assert speed_source.effective_speed_kmh == pytest.approx(62.0)
