"""Tests for order-reference and car domain objects."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from vibesensor.domain import Car, CarSnapshot
from vibesensor.domain.tire_spec import AxleTireSetup
from vibesensor.shared.order_reference_settings import (
    order_reference_mapping_from_spec,
    order_reference_spec_from_mapping,
)


def _order_settings(**overrides: float) -> dict[str, float]:
    settings = {
        "tire_width_mm": 285.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 21.0,
    }
    settings.update(overrides)
    return settings


# ---------------------------------------------------------------------------
# OrderReferenceSpec tests
# ---------------------------------------------------------------------------


class TestOrderReferenceSpecFromSettings:
    def test_returns_none_when_missing_tire_keys(self) -> None:
        assert order_reference_spec_from_mapping({"final_drive_ratio": 3.0}) is None

    def test_returns_spec_with_complete_tire_keys(self) -> None:
        settings = _order_settings(
            final_drive_ratio=3.08,
            current_gear_ratio=0.64,
            wheel_bandwidth_pct=5.0,
            driveshaft_bandwidth_pct=4.5,
            engine_bandwidth_pct=5.2,
            speed_uncertainty_pct=1.0,
            tire_diameter_uncertainty_pct=1.0,
            final_drive_uncertainty_pct=0.1,
            gear_uncertainty_pct=0.2,
            min_abs_band_hz=0.2,
            max_band_half_width_pct=6.0,
        )
        spec = order_reference_spec_from_mapping(settings, deflection_factor=0.97)
        assert spec is not None
        assert spec.tire_spec.width_mm == 285.0
        assert spec.final_drive_ratio == 3.08
        assert spec.current_gear_ratio == 0.64
        assert spec.tire_spec.deflection_factor == 0.97

    def test_missing_non_tire_keys_default_to_zero(self) -> None:
        settings = {"tire_width_mm": 205.0, "tire_aspect_pct": 55.0, "rim_in": 16.0}
        spec = order_reference_spec_from_mapping(settings)
        assert spec is not None
        assert spec.final_drive_ratio == 0.0
        assert spec.wheel_bandwidth_pct == 0.0

    def test_tire_circumference(self) -> None:
        settings = _order_settings()
        spec = order_reference_spec_from_mapping(settings)
        assert spec is not None
        assert spec.tire_circumference_m > 0
        assert spec.tire_circumference_m == spec.tire_spec.circumference_m

    def test_staggered_tire_setup_prefers_rear_axle_when_selected(self) -> None:
        spec = order_reference_spec_from_mapping(
            {
                "front_tire_width_mm": 245.0,
                "front_tire_aspect_pct": 40.0,
                "front_rim_in": 21.0,
                "rear_tire_width_mm": 275.0,
                "rear_tire_aspect_pct": 35.0,
                "rear_rim_in": 21.0,
                "default_axle_for_speed": "rear",
            }
        )
        assert spec is not None
        assert spec.tire_setup.is_staggered is True
        assert spec.tire_spec.width_mm == 275.0
        assert spec.tire_circumference_m == spec.tire_setup.rear.circumference_m

    def test_staggered_tire_setup_supports_average_effective_circumference(self) -> None:
        spec = order_reference_spec_from_mapping(
            {
                "front_tire_width_mm": 245.0,
                "front_tire_aspect_pct": 40.0,
                "front_rim_in": 21.0,
                "rear_tire_width_mm": 275.0,
                "rear_tire_aspect_pct": 35.0,
                "rear_rim_in": 21.0,
                "default_axle_for_speed": "average",
            }
        )
        assert spec is not None
        expected = (
            spec.tire_setup.front.circumference_m + spec.tire_setup.rear.circumference_m
        ) / 2.0
        assert spec.tire_circumference_m == expected

    def test_has_engine_reference(self) -> None:
        settings = _order_settings(current_gear_ratio=0.64)
        spec = order_reference_spec_from_mapping(settings)
        assert spec is not None
        assert spec.has_engine_reference is True

    def test_no_engine_reference_when_zero(self) -> None:
        settings = _order_settings(current_gear_ratio=0.0)
        spec = order_reference_spec_from_mapping(settings)
        assert spec is not None
        assert spec.has_engine_reference is False

    def test_is_complete(self) -> None:
        settings = _order_settings(final_drive_ratio=3.08)
        spec = order_reference_spec_from_mapping(settings)
        assert spec is not None
        assert spec.is_complete is True

    def test_not_complete_without_drive_ratio(self) -> None:
        settings = _order_settings()
        spec = order_reference_spec_from_mapping(settings)
        assert spec is not None
        assert spec.is_complete is False


class TestCarOrderReferenceSpec:
    @pytest.mark.parametrize(
        (
            "car",
            "expected_name",
            "expected_car_type",
            "expected_display_name",
            "expected_tire_width_mm",
            "expected_tire_aspect_pct",
            "expected_rim_in",
        ),
        [
            pytest.param(
                Car(),
                "Unnamed Car",
                "sedan",
                "Unnamed Car (sedan)",
                None,
                None,
                None,
                id="defaults",
            ),
            pytest.param(
                Car(name="Track Tool", car_type="coupe"),
                "Track Tool",
                "coupe",
                "Track Tool (coupe)",
                None,
                None,
                None,
                id="custom-type",
            ),
            pytest.param(
                Car(name="Test", aspects=_order_settings()),
                "Test",
                "sedan",
                "Test (sedan)",
                285.0,
                30.0,
                21.0,
                id="tire-aspects",
            ),
        ],
    )
    def test_car_derived_properties(
        self,
        car: Car,
        expected_name: str,
        expected_car_type: str,
        expected_display_name: str,
        expected_tire_width_mm: float | None,
        expected_tire_aspect_pct: float | None,
        expected_rim_in: float | None,
    ) -> None:
        assert car.name == expected_name
        assert car.car_type == expected_car_type
        assert car.display_name == expected_display_name
        assert car.tire_width_mm == expected_tire_width_mm
        assert car.tire_aspect_pct == expected_tire_aspect_pct
        assert car.rim_in == expected_rim_in

    @pytest.mark.parametrize(
        "key",
        [
            pytest.param("tire_width_mm", id="width"),
            pytest.param("tire_aspect_pct", id="aspect"),
            pytest.param("rim_in", id="rim"),
        ],
    )
    def test_car_rejects_zero_tire_dimension(self, key: str) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            Car(aspects={key: 0.0})

    def test_car_with_tire_aspects_has_spec(self) -> None:
        car = Car(
            aspects=_order_settings(final_drive_ratio=3.08),
        )
        assert car.order_reference_spec is not None
        assert car.order_reference_spec.final_drive_ratio == 3.08

    def test_car_without_tire_aspects_has_none(self) -> None:
        car = Car(aspects={"final_drive_ratio": 3.08})
        assert car.order_reference_spec is None

    def test_car_empty_aspects_has_none(self) -> None:
        car = Car()
        assert car.order_reference_spec is None

    def test_car_with_deflection_factor(self) -> None:
        car = Car(
            aspects=_order_settings(tire_deflection_factor=0.97),
        )
        assert car.order_reference_spec is not None
        assert car.order_reference_spec.tire_spec.deflection_factor == 0.97

    def test_car_projects_boundary_aspects_from_typed_spec(self) -> None:
        spec = order_reference_spec_from_mapping(
            {
                "tire_width_mm": 245.0,
                "tire_aspect_pct": 40.0,
                "rim_in": 18.0,
                "final_drive_ratio": 3.23,
                "current_gear_ratio": 0.82,
                "tire_deflection_factor": 0.97,
            },
        )
        assert spec is not None

        car = Car(
            order_reference_spec=spec,
            aspects={"tire_width_mm": 100.0, "tire_aspect_pct": 20.0, "rim_in": 10.0},
        )

        assert car.order_reference_spec is spec
        assert dict(car.aspects) == order_reference_mapping_from_spec(spec)
        assert car.tire_width_mm == 245.0
        assert car.tire_aspect_pct == 40.0
        assert car.rim_in == 18.0

    def test_car_projects_staggered_tire_setup_into_boundary_and_axle_fields(self) -> None:
        spec = order_reference_spec_from_mapping(
            {
                "front_tire_width_mm": 245.0,
                "front_tire_aspect_pct": 40.0,
                "front_rim_in": 21.0,
                "rear_tire_width_mm": 275.0,
                "rear_tire_aspect_pct": 35.0,
                "rear_rim_in": 21.0,
                "default_axle_for_speed": "rear",
            }
        )
        assert spec is not None

        car = Car(order_reference_spec=spec)

        assert car.tire_setup == AxleTireSetup(
            front=spec.tire_setup.front,
            rear=spec.tire_setup.rear,
            default_axle_for_speed="rear",
            source_confidence=None,
        )
        assert dict(car.aspects) == {
            "tire_width_mm": 275.0,
            "tire_aspect_pct": 35.0,
            "rim_in": 21.0,
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
            "front_tire_width_mm": 245.0,
            "front_tire_aspect_pct": 40.0,
            "front_rim_in": 21.0,
            "rear_tire_width_mm": 275.0,
            "rear_tire_aspect_pct": 35.0,
            "rear_rim_in": 21.0,
            "default_axle_for_speed": "rear",
        }

    def test_car_order_reference_properties_do_not_fall_back_to_aspects(self) -> None:
        car = Car(
            aspects={
                "tire_width_mm": 245.0,
                "tire_aspect_pct": 40.0,
                "rim_in": 18.0,
                "final_drive_ratio": 3.23,
            },
        )
        assert car.order_reference_spec is not None

        object.__setattr__(
            car,
            "_aspects",
            MappingProxyType(
                {
                    "tire_width_mm": 999.0,
                    "tire_aspect_pct": 1.0,
                    "rim_in": 1.0,
                },
            ),
        )

        assert car.tire_width_mm == 245.0
        assert car.tire_aspect_pct == 40.0
        assert car.rim_in == 18.0


def test_car_snapshot_aspects_mapping_is_immutable() -> None:
    source_aspects = {"a": 1.0}
    snap = CarSnapshot(aspects=source_aspects)

    source_aspects["a"] = 9.0
    assert dict(snap.aspects) == {"a": 1.0}

    with pytest.raises(TypeError):
        snap.aspects["b"] = 2.0
