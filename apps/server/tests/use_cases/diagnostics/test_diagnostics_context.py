from __future__ import annotations

from dataclasses import replace

from test_support.sample_scenarios import make_analysis_sample

from vibesensor.domain import Symptom
from vibesensor.shared.boundaries.runs.metadata import (
    run_metadata_from_mapping,
    run_metadata_to_json_object,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics._run_input import normalize_run_metadata
from vibesensor.use_cases.diagnostics.metadata_projection import metadata_analysis_settings_items
from vibesensor.use_cases.diagnostics.prepared_analysis_context import (
    prepare_analysis_context,
)
from vibesensor.use_cases.diagnostics.run_data_preparation import prepare_run_data
from vibesensor.use_cases.diagnostics.statistics import compute_accel_statistics


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


def _metadata() -> RunMetadata:
    return normalize_run_metadata(run_metadata_from_mapping(_context_metadata()), file_name="ctx")


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


def test_run_metadata_requires_nested_snapshot_for_context_fields() -> None:
    metadata = normalize_run_metadata(
        run_metadata_from_mapping(
            {
                "run_id": "legacy-run",
                "raw_sample_rate_hz": 200.0,
                "tire_width_mm": 225.0,
                "tire_aspect_pct": 45.0,
                "rim_in": 18.0,
                "final_drive_ratio": 3.55,
                "current_gear_ratio": 0.81,
                "car_name": "Legacy Car",
                "car_type": "sedan",
                "car_variant": "sport",
                "active_car_id": "car-legacy",
            },
        ),
        file_name="ctx",
    )

    projected = run_metadata_to_json_object(metadata)

    assert metadata.analysis_settings.final_drive_ratio == 0.0
    assert metadata.car is None
    assert projected["analysis_settings_snapshot"]["final_drive_ratio"] == 0.0
    assert "active_car_snapshot" not in projected


def test_run_metadata_drops_flat_analysis_settings_payload() -> None:
    metadata = normalize_run_metadata(
        run_metadata_from_mapping(
            {
                "run_id": "legacy-run",
                "raw_sample_rate_hz": 200.0,
                "analysis_settings": {"mode": "legacy"},
            },
        ),
        file_name="ctx",
    )

    projected = run_metadata_to_json_object(metadata)

    assert metadata_analysis_settings_items(metadata) == ()
    assert "analysis_settings" not in projected


def test_effective_order_reference_spec_applies_sample_ratio_overrides() -> None:
    metadata = _metadata()
    sample = replace(
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=80.0,
            client_name="front_left",
            top_peaks=[{"hz": 12.0, "amp": 0.02}],
        ),
        final_drive_ratio=4.1,
        gear=1.05,
    )

    spec = metadata.order_reference_spec_for(sample)

    assert spec is not None
    assert spec.final_drive_ratio == 4.1
    assert spec.current_gear_ratio == 1.05


def test_run_metadata_rehydrates_boundary_metadata_with_known_fields_only() -> None:
    metadata = _metadata()

    payload = run_metadata_to_json_object(metadata)

    assert payload["run_id"] == "ctx-run"
    assert payload["analysis_settings_snapshot"]["final_drive_ratio"] == 3.55
    assert payload["active_car_snapshot"]["variant"] == "sport"
    assert "aspects" not in payload["active_car_snapshot"]
    assert "reference_context" not in payload
    assert "tire_circumference_m" not in payload
    assert "analysis_settings" not in payload
    assert "custom_note" not in payload
    assert metadata_analysis_settings_items(metadata)[0][0] == "current_gear_ratio"


def test_prepare_analysis_context_builds_one_canonical_typed_summary_context() -> None:
    metadata = _metadata()
    samples = [
        replace(
            make_analysis_sample(
                t_s=0.0,
                speed_kmh=72.0,
                client_id="sensor-1",
                client_name="front_left",
                location="front-left",
                top_peaks=[{"hz": 12.0, "amp": 0.02}],
            ),
            vibration_strength_db=18.0,
            strength_bucket="l2",
        ),
        replace(
            make_analysis_sample(
                t_s=1.0,
                speed_kmh=74.0,
                client_id="sensor-1",
                client_name="front_left",
                location="front-left",
                top_peaks=[{"hz": 12.0, "amp": 0.03}],
            ),
            vibration_strength_db=19.0,
            strength_bucket="l2",
        ),
    ]

    prepared = prepare_run_data(metadata, samples)
    accel_stats = compute_accel_statistics(samples, metadata.sensor_model)
    analysis_context = prepare_analysis_context(
        context=metadata,
        samples=samples,
        file_name="ctx",
        language="en",
        include_samples=True,
        prepared=prepared,
        accel_stats=accel_stats,
    )

    assert analysis_context.context is metadata
    assert analysis_context.samples == tuple(samples)
    assert analysis_context.reference_complete is metadata.reference_complete
    assert analysis_context.overall_strength_band_key == "moderate"
    assert analysis_context.sensor_locations == ("front-left",)
    assert analysis_context.connected_locations == frozenset({"front-left"})
