"""Tests for shared run-context helpers."""

from __future__ import annotations

import json

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot, RunContextSnapshot
from vibesensor.shared.run_context import (
    apply_run_context_snapshot,
    build_run_context_snapshot,
    current_car_snapshot_token,
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


class TestApplyRunContextSnapshot:
    def test_serializes_snapshot_into_metadata_shape(self) -> None:
        metadata: dict[str, object] = {}

        apply_run_context_snapshot(
            metadata,
            analysis_settings_snapshot=AnalysisSettingsSnapshot(
                tire_width_mm=255.0,
                tire_aspect_pct=40.0,
                rim_in=19.0,
                final_drive_ratio=3.15,
                current_gear_ratio=0.81,
            ),
            active_car_snapshot=CarSnapshot(
                car_id="car-1",
                name="Primary",
                car_type="sedan",
                variant="track",
                aspects={"tire_width_mm": 255.0},
            ),
        )

        assert metadata["active_car_id"] == "car-1"
        assert metadata["car_name"] == "Primary"
        assert metadata["car_type"] == "sedan"
        assert metadata["car_variant"] == "track"
        assert metadata["analysis_settings_snapshot"] == {
            "tire_width_mm": 255.0,
            "tire_aspect_pct": 40.0,
            "rim_in": 19.0,
            "final_drive_ratio": 3.15,
            "current_gear_ratio": 0.81,
            "wheel_bandwidth_pct": 0.0,
            "driveshaft_bandwidth_pct": 0.0,
            "engine_bandwidth_pct": 0.0,
            "speed_uncertainty_pct": 0.0,
            "tire_diameter_uncertainty_pct": 0.0,
            "final_drive_uncertainty_pct": 0.0,
            "gear_uncertainty_pct": 0.0,
            "min_abs_band_hz": 0.0,
            "max_band_half_width_pct": 0.0,
            "tire_deflection_factor": 1.0,
        }
        assert metadata["active_car_snapshot"] == {
            "id": "car-1",
            "name": "Primary",
            "type": "sedan",
            "variant": "track",
            "aspects": {"tire_width_mm": 255.0},
        }

    def test_applies_car_fields_from_typed_snapshot(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original_to_metadata_dict = RunContextSnapshot.to_metadata_dict

        def _fake_to_metadata_dict(self: RunContextSnapshot) -> dict[str, object]:
            payload = original_to_metadata_dict(self)
            payload["active_car_snapshot"] = {
                "id": "persisted-id",
                "name": "Persisted Name",
                "type": "persisted-type",
                "variant": "persisted-variant",
                "aspects": {},
            }
            return payload

        monkeypatch.setattr(RunContextSnapshot, "to_metadata_dict", _fake_to_metadata_dict)
        metadata: dict[str, object] = {}

        apply_run_context_snapshot(
            metadata,
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            active_car_snapshot=CarSnapshot(
                car_id="typed-id",
                name="Typed Name",
                car_type="typed-type",
                variant="typed-variant",
            ),
        )

        assert metadata["active_car_id"] == "typed-id"
        assert metadata["car_name"] == "Typed Name"
        assert metadata["car_type"] == "typed-type"
        assert metadata["car_variant"] == "typed-variant"
        assert metadata["active_car_snapshot"] == {
            "id": "persisted-id",
            "name": "Persisted Name",
            "type": "persisted-type",
            "variant": "persisted-variant",
            "aspects": {},
        }

    def test_no_active_car_snapshot_keeps_car_fields_absent(self) -> None:
        metadata: dict[str, object] = {}

        apply_run_context_snapshot(
            metadata,
            analysis_settings_snapshot=AnalysisSettingsSnapshot(tire_width_mm=205.0),
            active_car_snapshot=None,
        )

        assert "active_car_snapshot" not in metadata
        assert "active_car_id" not in metadata
        assert "car_name" not in metadata
        assert "car_type" not in metadata
        assert "car_variant" not in metadata
        assert metadata["analysis_settings_snapshot"] == {
            "tire_width_mm": 205.0,
            "tire_aspect_pct": 0.0,
            "rim_in": 0.0,
            "final_drive_ratio": 0.0,
            "current_gear_ratio": 0.0,
            "wheel_bandwidth_pct": 0.0,
            "driveshaft_bandwidth_pct": 0.0,
            "engine_bandwidth_pct": 0.0,
            "speed_uncertainty_pct": 0.0,
            "tire_diameter_uncertainty_pct": 0.0,
            "final_drive_uncertainty_pct": 0.0,
            "gear_uncertainty_pct": 0.0,
            "min_abs_band_hz": 0.0,
            "max_band_half_width_pct": 0.0,
            "tire_deflection_factor": 1.0,
        }


class TestBoundaryHelpers:
    def test_order_reference_context_complete_stays_metadata_oriented(self) -> None:
        assert (
            order_reference_context_complete(
                {
                    "raw_sample_rate_hz": 800,
                    "tire_width_mm": 255.0,
                    "tire_aspect_pct": 40.0,
                    "rim_in": 19.0,
                    "final_drive_ratio": 3.15,
                    "current_gear_ratio": 0.81,
                },
            )
            is True
        )

    def test_current_car_snapshot_token_remains_stable_serialization(self) -> None:
        car = CarSnapshot(
            car_id="car-1",
            name="Primary",
            car_type="sedan",
            variant="track",
            aspects={"rim_in": 19.0, "tire_width_mm": 255.0},
        )

        token = current_car_snapshot_token(car)

        assert json.loads(token) == {
            "id": "car-1",
            "name": "Primary",
            "type": "sedan",
            "variant": "track",
            "aspects": {"rim_in": 19.0, "tire_width_mm": 255.0},
        }
