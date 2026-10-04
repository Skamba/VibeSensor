from __future__ import annotations

from vibesensor.analysis._run_input import normalize_run_metadata
from vibesensor.domain.diagnostic_case import Symptom
from vibesensor.recording.run_metadata import (
    run_metadata_from_mapping,
)


def _context_metadata() -> dict[str, object]:
    return {
        "run_id": "ctx-run",
        "start_time_utc": "2025-01-01T00:00:00Z",
        "end_time_utc": "2025-01-01T00:00:10Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "feature_interval_s": 0.5,
        "analysis_settings_snapshot": {
            "tire_width_mm": 225.0,
            "tire_aspect_pct": 45.0,
            "rim_in": 18.0,
            "final_drive_ratio": 3.55,
            "current_gear_ratio": 0.81,
        },
        "active_car_snapshot": {
            "id": "car-1",
            "name": "Primary",
            "type": "sedan",
            "variant": "sport",
        },
        "symptom": {
            "description": "driveline hum",
            "onset": "after 60 km/h",
            "context": "during acceleration",
        },
    }


def test_run_metadata_is_the_diagnostics_context() -> None:
    metadata_payload = _context_metadata()
    metadata_payload.update(
        {
            "final_drive_ratio": 9.99,
            "current_gear_ratio": 1.99,
            "car_name": "Flat Name",
            "car_type": "truck",
            "car_variant": "flat",
        },
    )
    metadata = normalize_run_metadata(run_metadata_from_mapping(metadata_payload), file_name="ctx")

    assert metadata.run_id == "ctx-run"
    assert metadata.raw_sample_rate_hz == 200.0
    assert metadata.sensor_model == "ADXL345"
    assert metadata.car_name == "Primary"
    assert metadata.car_variant == "sport"
    assert metadata.order_reference_spec is not None
    assert metadata.tire_circumference_m is not None
    assert metadata.reference_complete is True
    assert isinstance(metadata.symptom, Symptom)
    assert metadata.symptom is not None
    assert metadata.symptom.description == "driveline hum"
    assert metadata.symptom.onset == "after 60 km/h"
    assert metadata.symptom.context == "during acceleration"
    spec = metadata.order_reference_spec

    assert spec is not None
    assert spec.final_drive_ratio == 3.55
    assert spec.current_gear_ratio == 0.81
    assert metadata.car_name == "Primary"
    assert metadata.car_type == "sedan"
    assert metadata.car_variant == "sport"
