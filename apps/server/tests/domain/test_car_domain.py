"""Tests for OrderReferenceSpec and CarSnapshot domain objects."""

from __future__ import annotations

from types import MappingProxyType

from vibesensor.domain import Car, CarSnapshot, OrderReferenceSpec


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
        assert OrderReferenceSpec.from_settings({"final_drive_ratio": 3.0}) is None

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
        spec = OrderReferenceSpec.from_settings(settings, deflection_factor=0.97)
        assert spec is not None
        assert spec.tire_spec.width_mm == 285.0
        assert spec.final_drive_ratio == 3.08
        assert spec.current_gear_ratio == 0.64
        assert spec.tire_spec.deflection_factor == 0.97

    def test_missing_non_tire_keys_default_to_zero(self) -> None:
        settings = {"tire_width_mm": 205.0, "tire_aspect_pct": 55.0, "rim_in": 16.0}
        spec = OrderReferenceSpec.from_settings(settings)
        assert spec is not None
        assert spec.final_drive_ratio == 0.0
        assert spec.wheel_bandwidth_pct == 0.0

    def test_tire_circumference(self) -> None:
        settings = _order_settings()
        spec = OrderReferenceSpec.from_settings(settings)
        assert spec is not None
        assert spec.tire_circumference_m > 0
        assert spec.tire_circumference_m == spec.tire_spec.circumference_m

    def test_has_engine_reference(self) -> None:
        settings = _order_settings(current_gear_ratio=0.64)
        spec = OrderReferenceSpec.from_settings(settings)
        assert spec is not None
        assert spec.has_engine_reference is True

    def test_no_engine_reference_when_zero(self) -> None:
        settings = _order_settings(current_gear_ratio=0.0)
        spec = OrderReferenceSpec.from_settings(settings)
        assert spec is not None
        assert spec.has_engine_reference is False

    def test_is_complete(self) -> None:
        settings = _order_settings(final_drive_ratio=3.08)
        spec = OrderReferenceSpec.from_settings(settings)
        assert spec is not None
        assert spec.is_complete is True

    def test_not_complete_without_drive_ratio(self) -> None:
        settings = _order_settings()
        spec = OrderReferenceSpec.from_settings(settings)
        assert spec is not None
        assert spec.is_complete is False


class TestCarOrderReferenceSpec:
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
        spec = OrderReferenceSpec.from_settings(
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
        assert dict(car.aspects) == spec.to_settings_dict()
        assert car.tire_width_mm == 245.0
        assert car.tire_aspect_pct == 40.0
        assert car.rim_in == 18.0

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


# ---------------------------------------------------------------------------
# CarSnapshot tests
# ---------------------------------------------------------------------------


class TestCarSnapshot:
    def test_from_dict_empty(self) -> None:
        snap = CarSnapshot.from_dict({})
        assert snap.car_id is None
        assert snap.name is None
        assert snap.car_type is None
        assert snap.variant is None
        assert dict(snap.aspects) == {}

    def test_from_dict_full(self) -> None:
        snap = CarSnapshot.from_dict(
            {
                "id": "abc123",
                "name": "Test Car",
                "type": "sedan",
                "variant": "sport",
                "aspects": {"tire_width_mm": 205.0, "tire_aspect_pct": 55.0},
            }
        )
        assert snap.car_id == "abc123"
        assert snap.name == "Test Car"
        assert snap.car_type == "sedan"
        assert snap.variant == "sport"
        assert snap.aspects["tire_width_mm"] == 205.0

    def test_from_dict_with_id_key(self) -> None:
        snap = CarSnapshot.from_dict({"id": "xyz"})
        assert snap.car_id == "xyz"

    def test_to_dict_round_trip(self) -> None:
        original = CarSnapshot(
            car_id="abc",
            name="Test",
            car_type="suv",
            variant=None,
            aspects={"tire_width_mm": 205.0},
        )
        d = original.to_dict()
        assert d["id"] == "abc"
        assert d["name"] == "Test"
        reconstructed = CarSnapshot.from_dict(d)
        assert reconstructed.car_id == original.car_id
        assert reconstructed.name == original.name

    def test_aspects_frozen(self) -> None:
        snap = CarSnapshot(aspects={"a": 1.0})
        try:
            snap.aspects["b"] = 2.0
            raise AssertionError("Should not allow mutation")  # noqa: TRY301
        except TypeError:
            pass  # MappingProxyType raises TypeError on mutation

    def test_whitespace_name_becomes_none(self) -> None:
        snap = CarSnapshot.from_dict({"name": "  "})
        assert snap.name is None

    def test_invalid_aspects_skipped(self) -> None:
        snap = CarSnapshot.from_dict({"aspects": {"a": "not_a_number", "b": 1.5}})
        assert "a" not in snap.aspects
        assert snap.aspects["b"] == 1.5
