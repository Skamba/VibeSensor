"""Core grouped-picker behavior checks."""

from __future__ import annotations

from unittest.mock import patch

from vibesensor.domain.tire_spec import AxleTireSetup, TireSpec
from vibesensor.domain.vehicle_configuration import (
    VehicleConfiguration,
    VehicleConfigurationTireOption,
)
from vibesensor.settings.car_library import (
    get_brands,
    get_exact_configurations_for_variant,
    get_models_for_brand_type,
    get_types_for_brand,
    load_car_library,
)


def test_load_library_handles_bad_vehicle_configurations() -> None:
    with patch(
        "vibesensor.settings.car_library.load_vehicle_configurations",
        return_value=[],
    ):
        assert load_car_library() == []


def _tire(width: float, aspect: float, rim: float) -> TireSpec:
    return TireSpec(width_mm=width, aspect_pct=aspect, rim_in=rim)


def _option(
    name: str, tire: TireSpec, confidence: str, rear: TireSpec | None = None
) -> VehicleConfigurationTireOption:
    return VehicleConfigurationTireOption(
        name=name,
        tire_setup=AxleTireSetup(front=tire, rear=rear or tire, source_confidence=confidence),
    )


def _row(
    row_id: str,
    transmission: str,
    options: tuple[VehicleConfigurationTireOption, ...],
) -> VehicleConfiguration:
    return VehicleConfiguration(
        id=row_id,
        brand="BMW",
        car_type="Sedan",
        model_name="5 Series (F10, 2011)",
        variant_name="520i",
        drivetrain="RWD",
        transmission_name=transmission,
        top_gear_ratio=0.67,
        final_drive_rear=3.2,
        default_tire=options[0].tire_setup.front,
        tire_options=options,
    )


def test_variant_offers_the_union_of_its_rows_tire_options() -> None:
    """Every row's tire sizes reach the picker; a repeated size keeps its best source."""
    standard_17 = _tire(225, 55, 17)
    square_18 = _tire(245, 45, 18)
    staggered_rear_18 = _tire(275, 40, 18)
    manual = _row(
        "manual",
        "6-speed manual",
        (
            _option('Standard 17"', standard_17, "official_exact"),
            _option('18" square', square_18, "family_default"),
            _option('18" staggered', square_18, "official_exact", rear=staggered_rear_18),
        ),
    )
    automatic = _row(
        "automatic",
        "8-speed automatic",
        (
            _option('18" square', square_18, "official_exact"),
            _option('19" sport', _tire(245, 40, 19), "unverified"),
        ),
    )

    with patch(
        "vibesensor.settings.car_library.load_vehicle_configurations",
        return_value=[manual, automatic],
    ):
        [entry] = load_car_library()

    [variant] = entry["variants"]
    options = [
        (
            option["name"],
            option["front"]["width_mm"],
            option.get("rear"),
            option["source_confidence"],
        )
        for option in variant["tire_options"]
    ]
    assert options == [
        ('Standard 17"', 225, None, "official_exact"),
        ('18" square', 245, None, "official_exact"),
        (
            '18" staggered',
            245,
            {"width_mm": 275, "aspect_pct": 40, "rim_in": 18},
            "official_exact",
        ),
        ('19" sport', 245, None, "unverified"),
    ]
    assert [gearbox["name"] for gearbox in variant["gearboxes"]] == [
        "6-speed manual",
        "8-speed automatic",
    ]


def _size(setup: AxleTireSetup) -> tuple[float, ...]:
    return (
        setup.front.width_mm,
        setup.front.aspect_pct,
        setup.front.rim_in,
        setup.rear.width_mm,
        setup.rear.aspect_pct,
        setup.rear.rim_in,
    )


def test_bundled_picker_offers_every_exact_row_tire_size() -> None:
    """No bundled row's tire size is hidden behind another row of the same variant."""
    missing: list[str] = []
    for brand in get_brands():
        for car_type in get_types_for_brand(brand):
            for entry in get_models_for_brand_type(brand, car_type):
                for variant in entry["variants"]:
                    offered = set()
                    for option in variant["tire_options"]:
                        front = option["front"]
                        rear = option.get("rear", front)
                        offered.add(
                            (
                                front["width_mm"],
                                front["aspect_pct"],
                                front["rim_in"],
                                rear["width_mm"],
                                rear["aspect_pct"],
                                rear["rim_in"],
                            )
                        )
                    configs = get_exact_configurations_for_variant(
                        brand, car_type, entry["model"], variant["name"]
                    )
                    assert configs, (entry["model"], variant["name"])
                    for config in configs:
                        sizes = [_size(option.tire_setup) for option in config.tire_options]
                        if not sizes:
                            sizes = [_size(AxleTireSetup.square(config.default_tire))]
                        missing.extend(
                            f"{config.id}: {size}" for size in sizes if size not in offered
                        )
    assert not missing, "\n".join(missing)
