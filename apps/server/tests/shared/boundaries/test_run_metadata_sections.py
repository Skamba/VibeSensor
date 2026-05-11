from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import Symptom
from vibesensor.shared.boundaries.runs._metadata_codecs import (
    PayloadFieldSpec,
    decoded_values,
    float_decoder,
    include_if_not_none,
    int_decoder,
    optional_text_decoder,
    project_payload_fields,
    required_text_decoder,
)
from vibesensor.shared.boundaries.runs._metadata_sections import (
    reference_context_to_json_object,
    reference_tire_circumference,
    run_finalization_stage_to_json_object,
    run_finalization_stages_from_payload,
    run_raw_capture_finalize_from_payload,
    run_raw_capture_finalize_to_json_object,
    run_sensor_snapshot_to_json_object,
    run_sensor_snapshots_from_payload,
    symptom_from_payload,
    symptom_to_json_object,
)


@dataclass(frozen=True, slots=True)
class _ProjectionFixture:
    name: str
    optional_count: int | None


def test_metadata_codecs_decode_and_project_fields() -> None:
    specs = (
        PayloadFieldSpec("name", "name", required_text_decoder("name", "fallback")),
        PayloadFieldSpec("count", "count", int_decoder("count"), include=include_if_not_none),
        PayloadFieldSpec("ratio", "ratio", float_decoder("ratio"), include=include_if_not_none),
        PayloadFieldSpec(
            "note",
            "note",
            optional_text_decoder("note"),
            include=include_if_not_none,
        ),
    )

    decoded = decoded_values({"count": "7", "ratio": "2.5", "note": ""}, specs)
    projected = project_payload_fields(
        _ProjectionFixture(name="sensor", optional_count=None),
        (
            PayloadFieldSpec("name", "name", required_text_decoder("name")),
            PayloadFieldSpec(
                "optional_count",
                "optional_count",
                int_decoder("optional_count"),
                include=include_if_not_none,
            ),
        ),
    )

    assert decoded == {"name": "fallback", "count": 7, "ratio": 2.5, "note": None}
    assert projected == {"name": "sensor"}


def test_metadata_sections_decode_reference_context_and_symptom() -> None:
    symptom = symptom_from_payload(
        {"description": "whine", "onset": "above 60 km/h", "context": "under load"}
    )

    assert symptom is not None
    assert symptom.description == "whine"
    assert reference_tire_circumference({"tire_circumference_m": "2.12"}) == 2.12
    assert reference_context_to_json_object(2.12) == {"tire_circumference_m": 2.12}
    assert symptom_to_json_object(symptom) == {
        "description": "whine",
        "onset": "above 60 km/h",
        "context": "under load",
    }
    assert symptom_to_json_object(Symptom.unspecified()) is None


def test_metadata_sections_decode_sensor_snapshot_map_and_list_payloads() -> None:
    snapshots = run_sensor_snapshots_from_payload(
        {
            "sensor-b": {
                "client_name": "Rear",
                "location_code": "rear",
                "sample_rate_hz": "800",
            },
            "sensor-a": {
                "sensor_id": "sensor-a",
                "display_name": "Front",
                "location_code": "front",
                "mount_orientation": "radial",
            },
            "invalid": "skip",
        }
    )
    list_snapshots = run_sensor_snapshots_from_payload(
        [{"client_id": "sensor-c", "location_code": "center"}]
    )

    assert [snapshot.sensor_id for snapshot in snapshots] == ["sensor-a", "sensor-b"]
    assert snapshots[1].display_name == "Rear"
    assert snapshots[1].sample_rate_hz == 800
    assert run_sensor_snapshot_to_json_object(snapshots[0]) == {
        "sensor_id": "sensor-a",
        "display_name": "Front",
        "location_code": "front",
        "mount_orientation": "radial",
    }
    assert list_snapshots[0].sensor_id == "sensor-c"


def test_metadata_sections_decode_finalize_and_stage_payloads() -> None:
    finalize = run_raw_capture_finalize_from_payload(
        {"status": "timeout", "queue_depth": "3", "error_summary": "slow flush"}
    )
    invalid_finalize = run_raw_capture_finalize_from_payload({"status": "unknown"})
    stages = run_finalization_stages_from_payload(
        [
            {
                "stage_name": "FinalizeRawCaptureStage",
                "status": "degraded",
                "duration_ms": "-4",
                "artifacts_created": ["raw_capture_manifest"],
                "warnings": ["timeout"],
                "diagnostic_context": {"queue_depth": 3},
            },
            {"stage_name": "", "status": "ok", "duration_ms": 1},
            {"stage_name": "BadStatus", "status": "unknown", "duration_ms": 1},
        ]
    )

    assert finalize is not None
    assert finalize.status == "timeout"
    assert finalize.queue_depth == 3
    assert invalid_finalize is None
    assert run_raw_capture_finalize_to_json_object(finalize) == {
        "status": "timeout",
        "queue_depth": 3,
        "error_summary": "slow flush",
    }
    assert len(stages) == 1
    assert stages[0].duration_ms == 0
    assert run_finalization_stage_to_json_object(stages[0]) == {
        "stage_name": "FinalizeRawCaptureStage",
        "status": "degraded",
        "duration_ms": 0,
        "artifacts_created": ["raw_capture_manifest"],
        "warnings": ["timeout"],
        "diagnostic_context": {"queue_depth": 3},
    }
