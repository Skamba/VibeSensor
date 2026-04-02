"""Tests for run-context orchestration helpers."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot, RunContextSnapshot
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_CAR_SETTINGS_CHANGED,
    WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
    RunContextWarning,
)
from vibesensor.use_cases.run.run_context import (
    add_current_context_warnings,
    apply_run_context_snapshot,
    build_run_context_snapshot,
    order_reference_context_complete,
    run_context_snapshot_from_metadata,
)


def _analysis_settings_metadata(
    snapshot: AnalysisSettingsSnapshot,
) -> dict[str, float]:
    return asdict(snapshot)


class TestBuildRunContextSnapshot:
    def test_returns_typed_run_context_snapshot(self) -> None:
        settings = AnalysisSettingsSnapshot(tire_width_mm=255.0, rim_in=19.0)
        car = CarSnapshot(car_id="car-1", name="Primary", car_type="sedan")

        snapshot = build_run_context_snapshot(
            analysis_settings_snapshot=settings,
            active_car_snapshot=car,
        )

        assert snapshot == RunContextSnapshot(analysis_settings=settings, car=car)


class TestApplyRunContextSnapshot:
    def test_serializes_snapshot_into_metadata_shape(self) -> None:
        metadata: dict[str, object] = {}
        settings = AnalysisSettingsSnapshot(
            tire_width_mm=255.0,
            tire_aspect_pct=40.0,
            rim_in=19.0,
            final_drive_ratio=3.15,
            current_gear_ratio=0.81,
        )

        apply_run_context_snapshot(
            metadata,
            analysis_settings_snapshot=settings,
            active_car_snapshot=CarSnapshot(
                car_id="car-1",
                name="Primary",
                car_type="sedan",
                variant="track",
                aspects={"tire_width_mm": 255.0},
            ),
        )

        assert "active_car_id" not in metadata
        assert "car_name" not in metadata
        assert "car_type" not in metadata
        assert "car_variant" not in metadata
        assert metadata["analysis_settings_snapshot"] == _analysis_settings_metadata(settings)
        assert metadata["active_car_snapshot"] == {
            "id": "car-1",
            "name": "Primary",
            "type": "sedan",
            "variant": "track",
            "aspects": {"tire_width_mm": 255.0},
        }

    def test_no_active_car_snapshot_keeps_car_fields_absent(self) -> None:
        metadata: dict[str, object] = {}
        settings = AnalysisSettingsSnapshot(tire_width_mm=205.0)

        apply_run_context_snapshot(
            metadata,
            analysis_settings_snapshot=settings,
            active_car_snapshot=None,
        )

        assert "active_car_snapshot" not in metadata
        assert "active_car_id" not in metadata
        assert "car_name" not in metadata
        assert "car_type" not in metadata
        assert "car_variant" not in metadata
        assert metadata["analysis_settings_snapshot"] == _analysis_settings_metadata(settings)


class TestBoundaryHelpers:
    def test_run_context_snapshot_from_metadata_ignores_flat_legacy_fields(self) -> None:
        snapshot = run_context_snapshot_from_metadata(
            {
                "tire_width_mm": 255.0,
                "tire_aspect_pct": 40.0,
                "rim_in": 19.0,
                "final_drive_ratio": 3.15,
                "current_gear_ratio": 0.81,
                "car_name": "Legacy Car",
                "car_type": "wagon",
                "car_variant": "touring",
                "active_car_id": "legacy-1",
            },
        )

        assert snapshot.analysis_settings == AnalysisSettingsSnapshot()
        assert snapshot.car is None

    def test_run_context_snapshot_from_metadata_prefers_nested_snapshot_over_flat_aliases(
        self,
    ) -> None:
        snapshot = run_context_snapshot_from_metadata(
            {
                "analysis_settings_snapshot": {
                    "final_drive_ratio": 3.15,
                    "current_gear_ratio": 0.81,
                },
                "active_car_snapshot": {
                    "id": "nested-1",
                    "name": "Nested Car",
                    "type": "sedan",
                    "variant": "sport",
                    "aspects": {"final_drive_ratio": 3.15},
                },
                "final_drive_ratio": 9.99,
                "current_gear_ratio": 1.99,
                "car_name": "Flat Car",
                "car_type": "truck",
                "car_variant": "work",
                "active_car_id": "flat-1",
            },
        )

        assert snapshot.analysis_settings.final_drive_ratio == pytest.approx(3.15)
        assert snapshot.analysis_settings.current_gear_ratio == pytest.approx(0.81)
        assert snapshot.car is not None
        assert snapshot.car.car_id == "nested-1"
        assert snapshot.car.name == "Nested Car"
        assert snapshot.car.car_type == "sedan"
        assert snapshot.car.variant == "sport"

    def test_order_reference_context_complete_uses_canonical_snapshot_metadata(self) -> None:
        assert (
            order_reference_context_complete(
                {
                    "raw_sample_rate_hz": 800,
                    "analysis_settings_snapshot": {
                        "tire_width_mm": 255.0,
                        "tire_aspect_pct": 40.0,
                        "rim_in": 19.0,
                        "final_drive_ratio": 3.15,
                        "current_gear_ratio": 0.81,
                    },
                },
            )
            is True
        )


def test_add_current_context_warnings_returns_app_level_models() -> None:
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
        metadata={
            "active_car_snapshot": {
                "id": "car-a",
                "name": "Track Car",
                "type": "coupe",
                "aspects": {"tire_width_mm": 245.0},
            }
        },
        current_active_car_snapshot=CarSnapshot(
            car_id="car-b",
            name="Daily Car",
            car_type="wagon",
            aspects={"tire_width_mm": 225.0},
        ),
    )

    assert [warning.code for warning in warnings] == [
        WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
        WARNING_CODE_CAR_SETTINGS_CHANGED,
    ]
    assert all(isinstance(warning, RunContextWarning) for warning in warnings)
