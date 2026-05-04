from __future__ import annotations

import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
    build_whole_run_context_artifact_bundle,
    whole_run_context_labels_from_jsonl_bytes,
)


def _metadata():
    return run_metadata_from_mapping(
        {
            "run_id": "run-context-artifacts",
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 10,
            "sample_rate_hz": 10,
            "feature_interval_s": 1.0,
            "fft_window_size_samples": 10,
            "language": "en",
        }
    )


def test_build_whole_run_context_artifact_bundle_round_trips_labels_and_intervals() -> None:
    samples = sensor_frames_from_mappings(
        [
            {"t_s": 0.5, "speed_kmh": 0.0, "speed_source": "gps"},
            {"t_s": 1.5, "speed_kmh": 25.0, "speed_source": "gps", "engine_rpm": 1200.0},
            {"t_s": 2.5, "speed_kmh": 45.0, "speed_source": "gps", "engine_rpm": 1800.0},
            {"t_s": 3.5, "speed_kmh": 45.0, "speed_source": "gps", "engine_rpm": 1800.0},
        ]
    )

    bundle = build_whole_run_context_artifact_bundle(
        run_id="run-context-artifacts",
        metadata=_metadata(),
        samples=samples,
        total_sample_count=40,
        created_at="2025-01-01T00:00:01Z",
    )

    artifact = bundle.manifest.artifact(WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY)
    assert artifact is not None
    assert artifact.relative_path == "context/window-labels.jsonl"
    assert artifact.record_count == 4
    assert bundle.manifest.to_json_object() == {
        "schema_version": bundle.manifest.schema_version,
        "storage_type": bundle.manifest.storage_type,
        "run_id": "run-context-artifacts",
        "relative_dir": "whole-run-artifacts/run-context-artifacts",
        "window_policy": bundle.manifest.window_policy.to_json_object(),
        "total_window_count": 4,
        "artifacts": [
            {
                "artifact_key": WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
                "relative_path": "context/window-labels.jsonl",
                "file_format": "jsonl",
                "record_count": 4,
            }
        ],
        "created_at": "2025-01-01T00:00:01Z",
        "generated_artifact_paths": {
            WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY: "context/window-labels.jsonl",
        },
        "algorithm_versions": {},
        "configuration": {},
        "source_raw_manifests": [],
    }
    assert len(bundle.labels) == 4
    assert len(bundle.intervals) >= 1
    assert bundle.intervals[0].start_window_index == 0
    assert bundle.intervals[-1].end_window_index == 3

    reloaded = whole_run_context_labels_from_jsonl_bytes(
        bundle.artifact_contents[WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY]
    )
    assert reloaded == bundle.labels


def test_whole_run_context_labels_from_jsonl_bytes_handles_empty_payload() -> None:
    assert whole_run_context_labels_from_jsonl_bytes(b"") == ()


def test_whole_run_context_labels_from_jsonl_bytes_rejects_non_object_rows() -> None:
    with pytest.raises(
        ValueError,
        match="whole-run context label line must decode to a JSON object",
    ):
        whole_run_context_labels_from_jsonl_bytes(b"[]\n")
