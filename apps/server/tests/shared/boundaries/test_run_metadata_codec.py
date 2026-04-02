from __future__ import annotations

from vibesensor.shared.boundaries.run_metadata_codec import (
    run_metadata_from_mapping,
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
