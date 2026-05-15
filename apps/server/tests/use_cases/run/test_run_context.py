"""Tests for run-context orchestration helpers."""

from __future__ import annotations

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot, RunContextSnapshot
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_CAR_SETTINGS_CHANGED,
    WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
    RunContextWarning,
)
from vibesensor.use_cases.run.run_context import (
    add_current_context_warnings,
    build_run_context_snapshot,
    order_reference_context_complete,
)


class TestBuildRunContextSnapshot:
    def test_returns_typed_run_context_snapshot(self) -> None:
        settings = AnalysisSettingsSnapshot(tire_width_mm=255.0, rim_in=19.0)
        car = CarSnapshot(car_id="car-1", name="Primary", car_type="sedan")

        snapshot = build_run_context_snapshot(
            analysis_settings_snapshot=settings,
            active_car_snapshot=car,
        )

        assert snapshot == RunContextSnapshot(analysis_settings=settings, car=car)


class TestOrderReferenceContextComplete:
    @pytest.mark.parametrize(
        ("metadata_payload", "expected"),
        [
            (
                {
                    "run_id": "run-1",
                    "start_time_utc": "2025-01-01T00:00:00Z",
                    "sensor_model": "fixture-sensor",
                    "raw_sample_rate_hz": 800,
                    "analysis_settings_snapshot": {
                        "tire_width_mm": 255.0,
                        "tire_aspect_pct": 40.0,
                        "rim_in": 19.0,
                        "final_drive_ratio": 3.15,
                        "current_gear_ratio": 0.81,
                    },
                },
                True,
            ),
            (
                {
                    "run_id": "run-legacy",
                    "start_time_utc": "2025-01-01T00:00:00Z",
                    "sensor_model": "fixture-sensor",
                    "raw_sample_rate_hz": 800,
                    "tire_width_mm": 255.0,
                    "tire_aspect_pct": 40.0,
                    "rim_in": 19.0,
                    "final_drive_ratio": 3.15,
                    "current_gear_ratio": 0.81,
                },
                False,
            ),
        ],
        ids=["nested-snapshot", "flat-legacy-aliases"],
    )
    def test_order_reference_context_uses_only_canonical_nested_metadata(
        self,
        metadata_payload: dict[str, object],
        expected: bool,
    ) -> None:
        metadata = run_metadata_from_mapping(
            metadata_payload,
        )

        assert order_reference_context_complete(metadata) is expected


class TestCurrentContextWarnings:
    def test_returns_app_level_models(self) -> None:
        warnings = add_current_context_warnings(
            [
                RunContextWarning(
                    code=WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
                    severity="warn",
                    applies_to="order_analysis",
                    title={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
                    detail={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
                )
            ],
            metadata=run_metadata_from_mapping(
                {
                    "analysis_settings_snapshot": {
                        "tire_width_mm": 245.0,
                        "tire_aspect_pct": 40.0,
                        "rim_in": 19.0,
                    },
                    "active_car_snapshot": {
                        "id": "car-a",
                        "name": "Track Car",
                        "type": "coupe",
                    },
                }
            ),
            current_active_car_snapshot=CarSnapshot(
                car_id="car-b",
                name="Daily Car",
                car_type="wagon",
                aspects={"tire_width_mm": 225.0, "tire_aspect_pct": 45.0, "rim_in": 18.0},
            ),
        )

        assert [warning.code for warning in warnings] == [
            WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
            WARNING_CODE_CAR_SETTINGS_CHANGED,
        ]
        assert all(isinstance(warning, RunContextWarning) for warning in warnings)

    def test_supports_typed_metadata_without_boundary_reprojection(self) -> None:
        metadata = run_metadata_from_mapping(
            {
                "run_id": "run-1",
                "raw_sample_rate_hz": 800,
                "analysis_settings_snapshot": {
                    "tire_width_mm": 245.0,
                    "tire_aspect_pct": 40.0,
                    "rim_in": 19.0,
                },
                "active_car_snapshot": {
                    "id": "car-a",
                    "name": "Track Car",
                    "type": "coupe",
                },
            },
        )

        warnings = add_current_context_warnings(
            None,
            metadata=metadata,
            current_active_car_snapshot=CarSnapshot(
                car_id="car-b",
                name="Daily Car",
                car_type="wagon",
                aspects={"tire_width_mm": 225.0, "tire_aspect_pct": 45.0, "rim_in": 18.0},
            ),
        )

        assert [warning.code for warning in warnings] == [WARNING_CODE_CAR_SETTINGS_CHANGED]


def test_build_run_context_snapshot_keeps_missing_car_optional() -> None:
    snapshot = build_run_context_snapshot(
        analysis_settings_snapshot=AnalysisSettingsSnapshot(tire_width_mm=205.0),
        active_car_snapshot=None,
    )

    assert snapshot.analysis_settings == AnalysisSettingsSnapshot(tire_width_mm=205.0)
    assert snapshot.car is None
