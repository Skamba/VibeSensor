from __future__ import annotations

from dataclasses import replace

from test_support.sample_scenarios import make_analysis_sample

from vibesensor.domain import Symptom
from vibesensor.use_cases.diagnostics._context_decode import build_diagnostics_context
from vibesensor.use_cases.diagnostics._context_projection import context_to_metadata_dict


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
            "aspects": {
                "tire_width_mm": 225.0,
                "tire_aspect_pct": 45.0,
                "rim_in": 18.0,
                "final_drive_ratio": 3.55,
                "current_gear_ratio": 0.81,
            },
        },
        "symptom": "driveline hum",
        "symptom_onset": "after 60 km/h",
        "symptom_context": "during acceleration",
    }


def _context():
    return build_diagnostics_context(_context_metadata(), file_name="ctx")


def test_diagnostics_context_decodes_typed_reference_data() -> None:
    context = _context()

    assert context.run_id == "ctx-run"
    assert not hasattr(context, "run_metadata")
    assert context.raw_sample_rate_hz == 200.0
    assert context.sensor_model == "ADXL345"
    assert context.car_name == "Primary"
    assert context.car_variant == "sport"
    assert context.order_reference_spec is not None
    assert context.tire_circumference_m is not None
    assert context.reference_complete is True
    assert isinstance(context.symptom, Symptom)
    assert context.symptom is not None
    assert context.symptom.description == "driveline hum"
    assert context.symptom.onset == "after 60 km/h"
    assert context.symptom.context == "during acceleration"


def test_diagnostics_context_prefers_nested_snapshot_over_conflicting_flat_aliases() -> None:
    metadata = _context_metadata()
    metadata.update(
        {
            "final_drive_ratio": 9.99,
            "current_gear_ratio": 1.99,
            "car_name": "Flat Name",
            "car_type": "truck",
            "car_variant": "flat",
        },
    )

    context = build_diagnostics_context(metadata, file_name="ctx")
    spec = context.order_reference_spec

    assert spec is not None
    assert spec.final_drive_ratio == 3.55
    assert spec.current_gear_ratio == 0.81
    assert context.car_name == "Primary"
    assert context.car_type == "sedan"
    assert context.car_variant == "sport"


def test_diagnostics_context_requires_nested_snapshot_for_run_context_fields() -> None:
    context = build_diagnostics_context(
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
        file_name="ctx",
    )

    projected = context_to_metadata_dict(context)

    assert context.analysis_settings.final_drive_ratio == 0.0
    assert context.car is None
    assert projected["analysis_settings_snapshot"]["final_drive_ratio"] == 0.0
    assert "active_car_snapshot" not in projected


def test_diagnostics_context_drops_flat_analysis_settings_payload() -> None:
    context = build_diagnostics_context(
        {
            "run_id": "legacy-run",
            "raw_sample_rate_hz": 200.0,
            "analysis_settings": {"mode": "legacy"},
        },
        file_name="ctx",
    )

    metadata = context_to_metadata_dict(context)

    assert context.analysis_settings_items == ()
    assert "analysis_settings" not in metadata


def test_effective_order_reference_spec_applies_sample_ratio_overrides() -> None:
    context = _context()
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

    spec = context.effective_order_reference_spec(sample)

    assert spec is not None
    assert spec.final_drive_ratio == 4.1
    assert spec.current_gear_ratio == 1.05


def test_diagnostics_context_rehydrates_boundary_metadata_with_known_fields_only() -> None:
    context = _context()

    metadata = context_to_metadata_dict(context)

    assert metadata["run_id"] == "ctx-run"
    assert metadata["analysis_settings_snapshot"]["final_drive_ratio"] == 3.55
    assert metadata["active_car_snapshot"]["variant"] == "sport"
    assert metadata["tire_circumference_m"] is not None
    assert "analysis_settings" not in metadata
    assert "custom_note" not in metadata
    assert context.analysis_settings_items[0][0] == "current_gear_ratio"
