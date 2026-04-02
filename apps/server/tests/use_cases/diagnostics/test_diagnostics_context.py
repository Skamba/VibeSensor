from __future__ import annotations

from dataclasses import replace

from test_support.sample_scenarios import make_analysis_sample

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
        "analysis_settings": {"mode": "test", "window": 256},
        "symptom": "driveline hum",
        "symptom_onset": "after 60 km/h",
        "symptom_context": "during acceleration",
        "custom_note": "preserve-me",
    }


def _context():
    return build_diagnostics_context(_context_metadata(), file_name="ctx")


def test_diagnostics_context_decodes_typed_reference_data() -> None:
    context = _context()

    assert context.run_id == "ctx-run"
    assert context.raw_sample_rate_hz == 200.0
    assert context.sensor_model == "ADXL345"
    assert context.car_name == "Primary"
    assert context.car_variant == "sport"
    assert context.order_reference_spec is not None
    assert context.tire_circumference_m is not None
    assert context.reference_complete is True


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

    assert context.run_context.analysis_settings.final_drive_ratio == 0.0
    assert context.run_context.car is None
    assert projected["analysis_settings_snapshot"]["final_drive_ratio"] == 0.0
    assert "active_car_snapshot" not in projected


def test_diagnostics_context_preserves_legacy_flat_ratio_fallback_without_tire_geometry() -> None:
    context = build_diagnostics_context(
        {
            "run_id": "legacy-run",
            "raw_sample_rate_hz": 200.0,
            "tire_circumference_m": 2.036,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
        },
        file_name="ctx",
    )

    assert context.order_reference_spec is None
    assert context.tire_circumference_m == 2.036
    assert context.final_drive_ratio is None
    assert context.current_gear_ratio is None
    assert context.reference_complete is False


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


def test_diagnostics_context_rehydrates_boundary_metadata_with_known_and_unknown_fields() -> None:
    context = _context()

    metadata = context_to_metadata_dict(context)

    assert metadata["run_id"] == "ctx-run"
    assert metadata["custom_note"] == "preserve-me"
    assert metadata["analysis_settings_snapshot"]["final_drive_ratio"] == 3.55
    assert metadata["active_car_snapshot"]["variant"] == "sport"
    assert metadata["tire_circumference_m"] is not None
    assert context.scalar_analysis_settings == (("mode", "test"), ("window", 256))
