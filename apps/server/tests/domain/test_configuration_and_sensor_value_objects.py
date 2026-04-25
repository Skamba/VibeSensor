"""Domain value-object tests for configuration snapshots and sensors."""

from __future__ import annotations

from vibesensor.domain import (
    ConfigurationSnapshot,
    DiagnosticCase,
    Finding,
    RunCapture,
    Sensor,
    SensorPlacement,
    TestRun,
)
from vibesensor.shared.boundaries.runs.capture import configuration_snapshot_from_metadata
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping


def _metadata(**overrides: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "run_id": "cfg-run",
        "start_time_utc": "2025-01-01T00:00:00Z",
    }
    metadata.update(overrides)
    return metadata


class TestConfigurationSnapshot:
    """Tests for ConfigurationSnapshot construction, freezing, and case attachment."""

    def test_from_metadata_extracts_typed_fields(self) -> None:
        md = _metadata(
            sensor_model="MPU6050",
            firmware_version="1.2.3",
            strength_algorithm_version="strength-db-scalar-v1",
            peak_detector_version="peak-band-rms-v1",
            calibration_profile_id="noise-floor-p20-v1",
            vehicle_baseline_profile_id="car-profile-1",
            raw_sample_rate_hz=100.0,
            feature_interval_s=0.5,
            analysis_settings_snapshot={
                "final_drive_ratio": 3.73,
                "tire_width_mm": 205,
                "tire_aspect_pct": 55,
                "rim_in": 16,
            },
        )
        snap = configuration_snapshot_from_metadata(run_metadata_from_mapping(md))
        assert snap.sensor_model == "MPU6050"
        assert snap.firmware_version == "1.2.3"
        assert snap.strength_algorithm_version == "strength-db-scalar-v1"
        assert snap.peak_detector_version == "peak-band-rms-v1"
        assert snap.calibration_profile_id == "noise-floor-p20-v1"
        assert snap.vehicle_baseline_profile_id == "car-profile-1"
        assert snap.raw_sample_rate_hz == 100.0
        assert snap.feature_interval_s == 0.5
        assert snap.final_drive_ratio == 3.73
        assert snap.tire_spec is not None

    def test_from_metadata_with_empty_dict(self) -> None:
        snap = configuration_snapshot_from_metadata(run_metadata_from_mapping(_metadata()))
        assert snap.sensor_model is None
        assert snap.firmware_version is None
        assert snap.strength_algorithm_version is None
        assert snap.peak_detector_version is None
        assert snap.calibration_profile_id is None
        assert snap.vehicle_baseline_profile_id is None
        assert snap.raw_sample_rate_hz is None
        assert snap.feature_interval_s is None
        assert snap.final_drive_ratio is None

    def test_from_metadata_coerces_string_floats(self) -> None:
        md = _metadata(
            raw_sample_rate_hz="100.0",
            feature_interval_s="0.5",
            analysis_settings_snapshot={"final_drive_ratio": "3.73"},
        )
        snap = configuration_snapshot_from_metadata(run_metadata_from_mapping(md))
        assert snap.raw_sample_rate_hz == 100.0
        assert snap.feature_interval_s == 0.5
        assert snap.final_drive_ratio == 3.73

    def test_snapshot_no_longer_carries_raw_metadata_blob(self) -> None:
        snap = configuration_snapshot_from_metadata(
            run_metadata_from_mapping(_metadata(sensor_model="MPU6050"))
        )
        assert not hasattr(snap, "metadata")

    def test_empty_snapshot_equality(self) -> None:
        assert ConfigurationSnapshot() == ConfigurationSnapshot()

    def test_from_metadata_ignores_non_configuration_fields(self) -> None:
        md = _metadata(sensor_model="MPU6050", custom_key="custom_value")
        snap = configuration_snapshot_from_metadata(run_metadata_from_mapping(md))
        assert snap.sensor_model == "MPU6050"
        assert not hasattr(snap, "metadata")

    def test_case_snapshot_accessible_via_capture(self) -> None:
        snap_a = configuration_snapshot_from_metadata(
            run_metadata_from_mapping(_metadata(sensor_model="MPU6050"))
        )
        snap_b = configuration_snapshot_from_metadata(
            run_metadata_from_mapping(_metadata(sensor_model="BMI270"))
        )

        from vibesensor.domain import RunSetup

        finding = Finding(suspected_source="wheel/tire", confidence=0.8)
        case = DiagnosticCase(case_id="case-snap")
        case = case.add_run(
            TestRun(
                capture=RunCapture(run_id="r1", setup=RunSetup(configuration_snapshot=snap_a)),
                findings=(finding,),
                top_causes=(finding,),
            )
        )
        case = case.add_run(
            TestRun(
                capture=RunCapture(run_id="r2", setup=RunSetup(configuration_snapshot=snap_b)),
                findings=(finding,),
                top_causes=(finding,),
            )
        )
        assert case.test_runs[0].capture.setup.configuration_snapshot == snap_a
        assert case.test_runs[1].capture.setup.configuration_snapshot == snap_b


class TestSensor:
    def test_from_location_codes_creates_sensors(self) -> None:
        sensors = Sensor.from_location_codes(["front_left_wheel", "rear_axle"])
        assert len(sensors) == 2
        assert sensors[0].sensor_id == "front_left_wheel"
        assert sensors[0].placement is not None
        assert sensors[0].placement.code == "front_left_wheel"
        assert sensors[1].sensor_id == "rear_axle"
        assert sensors[1].placement is not None
        assert sensors[1].placement.code == "rear_axle"

    def test_from_location_codes_empty(self) -> None:
        sensors = Sensor.from_location_codes([])
        assert sensors == ()

    def test_sensor_equality(self) -> None:
        placement = SensorPlacement.from_code("front_left_wheel")
        a = Sensor(sensor_id="front_left_wheel", placement=placement)
        b = Sensor(sensor_id="front_left_wheel", placement=placement)
        assert a == b
