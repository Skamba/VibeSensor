from __future__ import annotations

import msgspec

from vibesensor.shared.boundaries.runs.metadata import (
    run_metadata_from_json,
    run_metadata_from_mapping,
    run_metadata_to_json_bytes,
    run_metadata_to_json_object,
)


def test_run_metadata_codec_roundtrip_uses_nested_symptom_and_reference_context() -> None:
    metadata = run_metadata_from_mapping(
        {
            "run_id": "run-1",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "sensor_model": "ADXL345",
            "symptom": {
                "description": "whine under load",
                "onset": "after 60 km/h",
                "context": "during acceleration",
            },
            "reference_context": {"tire_circumference_m": 2.2},
        }
    )

    assert metadata.symptom is not None
    assert metadata.symptom.description == "whine under load"
    assert metadata.symptom.onset == "after 60 km/h"
    assert metadata.symptom.context == "during acceleration"
    assert metadata.wheel_circumference_m == 2.2

    payload = run_metadata_to_json_object(metadata)

    assert payload["symptom"] == {
        "description": "whine under load",
        "onset": "after 60 km/h",
        "context": "during acceleration",
    }
    assert payload["reference_context"] == {"tire_circumference_m": 2.2}
    assert "symptom_onset" not in payload
    assert "symptom_context" not in payload
    assert "tire_circumference_m" not in payload


def test_run_metadata_msgspec_codec_roundtrip_preserves_nested_fields() -> None:
    metadata = run_metadata_from_mapping(
        {
            "run_id": "run-msgspec",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "sensor_model": "ADXL345",
            "symptom": {
                "description": "whine under load",
                "onset": "after 60 km/h",
                "context": "during acceleration",
            },
            "reference_context": {"tire_circumference_m": 2.2},
        }
    )

    decoded = run_metadata_from_json(run_metadata_to_json_bytes(metadata))

    assert decoded.run_id == "run-msgspec"
    assert decoded.symptom is not None
    assert decoded.symptom.description == "whine under load"
    assert decoded.symptom.onset == "after 60 km/h"
    assert decoded.symptom.context == "during acceleration"
    assert decoded.wheel_circumference_m == 2.2


def test_run_metadata_from_json_tolerates_legacy_non_string_record_type() -> None:
    decoded = run_metadata_from_json(
        msgspec.json.encode(
            {
                "record_type": 123,
                "schema_version": "v2-jsonl",
                "run_id": "legacy-run",
                "start_time_utc": "2026-01-01T00:00:00Z",
                "sensor_model": "ADXL345",
            }
        )
    )

    assert decoded.record_type == "run_metadata"
    assert decoded.run_id == "legacy-run"


def test_run_metadata_codec_roundtrip_preserves_sensor_snapshots() -> None:
    metadata = run_metadata_from_mapping(
        {
            "run_id": "run-sensors",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "sensor_model": "ADXL345",
            "strength_algorithm_version": "strength-db-scalar-v1",
            "peak_detector_version": "peak-band-rms-v1",
            "calibration_profile_id": "noise-floor-p20-v1",
            "vehicle_baseline_profile_id": "car-profile-1",
            "sensor_snapshots": [
                {
                    "sensor_id": "sensor-a",
                    "display_name": "Front left",
                    "location_code": "front_left_wheel",
                    "mount_orientation": "radial",
                    "sample_rate_hz": 800,
                    "firmware_version": "1.2.3",
                }
            ],
        }
    )

    payload = run_metadata_to_json_object(metadata)
    decoded = run_metadata_from_json(run_metadata_to_json_bytes(metadata))

    assert payload["sensor_snapshots"] == [
        {
            "sensor_id": "sensor-a",
            "display_name": "Front left",
            "location_code": "front_left_wheel",
            "mount_orientation": "radial",
            "sample_rate_hz": 800,
            "firmware_version": "1.2.3",
        }
    ]
    assert payload["strength_algorithm_version"] == "strength-db-scalar-v1"
    assert payload["peak_detector_version"] == "peak-band-rms-v1"
    assert payload["calibration_profile_id"] == "noise-floor-p20-v1"
    assert payload["vehicle_baseline_profile_id"] == "car-profile-1"
    assert len(decoded.sensor_snapshots) == 1
    assert decoded.strength_algorithm_version == "strength-db-scalar-v1"
    assert decoded.peak_detector_version == "peak-band-rms-v1"
    assert decoded.calibration_profile_id == "noise-floor-p20-v1"
    assert decoded.vehicle_baseline_profile_id == "car-profile-1"
    snapshot = decoded.sensor_snapshots[0]
    assert snapshot.sensor_id == "sensor-a"
    assert snapshot.display_name == "Front left"
    assert snapshot.location_code == "front_left_wheel"
    assert snapshot.mount_orientation == "radial"
    assert snapshot.sample_rate_hz == 800
    assert snapshot.firmware_version == "1.2.3"


def test_run_metadata_codec_tolerates_missing_calibration_metadata_for_legacy_runs() -> None:
    metadata = run_metadata_from_mapping(
        {
            "run_id": "legacy-run",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "sensor_model": "ADXL345",
            "sensor_snapshots": [{"sensor_id": "sensor-a", "location_code": "front_left_wheel"}],
        }
    )

    assert metadata.strength_algorithm_version is None
    assert metadata.peak_detector_version is None
    assert metadata.calibration_profile_id is None
    assert metadata.vehicle_baseline_profile_id is None
    assert metadata.sensor_snapshots[0].mount_orientation is None
