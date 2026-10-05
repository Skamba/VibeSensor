"""Core grouped-picker behavior checks."""

from __future__ import annotations

from unittest.mock import patch

from vibesensor.domain.tire_spec import AxleTireSetup, TireSpec
from vibesensor.domain.vehicle_configuration import (
    VehicleConfiguration,
    VehicleConfigurationTireOption,
)
from vibesensor.settings import car_library
from vibesensor.settings.car_library import (
    get_brands,
    get_exact_configurations_for_variant,
    get_models_for_brand_type,
    get_types_for_brand,
    load_car_library,
)
from vibesensor.settings.vehicle_configurations import load_vehicle_configurations


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
    *,
    model_name: str = "5 Series (F10, 2011)",
    variant: str = "520i",
    years: tuple[int, int] | None = None,
    final_drive: float = 3.2,
) -> VehicleConfiguration:
    return VehicleConfiguration(
        id=row_id,
        brand="BMW",
        car_type="Sedan",
        model_name=model_name,
        model_code="F10",
        production_start_year=years[0] if years else None,
        production_end_year=years[1] if years else None,
        variant_name=variant,
        drivetrain="RWD",
        transmission_name=transmission,
        top_gear_ratio=0.67,
        final_drive_rear=final_drive,
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


def test_picker_groups_a_generation_and_resolves_the_year_in_the_variant() -> None:
    """Year-labelled rows of one generation become one model with its year range.

    A variant keeps one entry while its gearbox names are unique. When a
    gearbox repeats across years, the variant is offered per model-year
    period; a gearbox sold throughout appears in every period.
    """
    tires = (_option("Standard", _tire(225, 55, 17), "official_exact"),)
    early_auto = _row(
        "early-auto",
        "8-speed automatic",
        tires,
        model_name="5 Series (F10, 2010-2013)",
        variant="530d",
        years=(2010, 2013),
        final_drive=2.81,
    )
    manual = _row(
        "manual",
        "6-speed manual",
        tires,
        model_name="5 Series (F10, 2010-2017)",
        variant="530d",
        years=(2010, 2017),
    )
    late_auto = _row(
        "late-auto",
        "8-speed automatic",
        tires,
        model_name="5 Series (F10, 2014-2017)",
        variant="530d",
        years=(2014, 2017),
        final_drive=2.56,
    )
    other = _row(
        "other",
        "8-speed automatic",
        tires,
        model_name="5 Series (F10, 2014-2017)",
        variant="520d",
        years=(2014, 2017),
    )
    rows = [late_auto, other, manual, early_auto]

    [entry], rows_by_variant = car_library._build_grouped_library(rows)

    assert entry["model"] == "5 Series (F10, 2010\u20132017)"
    picked = {
        variant["name"]: (
            variant.get("production_start_year"),
            variant.get("production_end_year"),
            [(gearbox["name"], gearbox["final_drive_ratio"]) for gearbox in variant["gearboxes"]],
        )
        for variant in entry["variants"]
    }
    assert picked == {
        "520d": (2014, 2017, [("8-speed automatic", 3.2)]),
        "530d (2010\u20132013)": (
            2010,
            2013,
            [("6-speed manual", 3.2), ("8-speed automatic", 2.81)],
        ),
        "530d (2014\u20132017)": (
            2014,
            2017,
            [("6-speed manual", 3.2), ("8-speed automatic", 2.56)],
        ),
    }
    key = ("BMW", "Sedan", entry["model"])
    assert rows_by_variant[(*key, "530d (2014\u20132017)")] == (manual, late_auto)
    assert rows_by_variant[(*key, "520d")] == (other,)


def test_bundled_picker_reaches_every_exact_row_once_per_gearbox_choice() -> None:
    """A picker selection (model, variant, gearbox) names exactly one exact row.

    Every bundled row is offered as a gearbox of some picker variant, a
    variant never lists the same gearbox twice, and each model family has
    one picker entry per generation code. Gearboxes carry their row's
    ICE/PHEV/EV powertrain for the saved car.
    """
    reached: set[str | None] = set()
    fuel_types: set[str] = set()
    families: dict[tuple[str, str, str], list[str]] = {}
    for entry in load_car_library():
        family = entry["model"].split(",")[0]
        families.setdefault((entry["brand"], entry["type"], family), []).append(entry["model"])
        for variant in entry["variants"]:
            configs = get_exact_configurations_for_variant(
                entry["brand"], entry["type"], entry["model"], variant["name"]
            )
            names = [gearbox["name"] for gearbox in variant["gearboxes"]]
            assert len(set(names)) == len(names), (entry["model"], variant["name"])
            assert names == [config.transmission_name for config in configs]
            assert [gearbox["final_drive_ratio"] for gearbox in variant["gearboxes"]] == [
                config.driven_final_drive_ratio for config in configs
            ]
            assert [gearbox["fuel_type"] for gearbox in variant["gearboxes"]] == [
                config.fuel_type for config in configs
            ]
            fuel_types.update(config.fuel_type for config in configs)
            reached.update(config.id for config in configs)
    assert fuel_types == {"ICE", "PHEV", "EV"}
    assert reached == {config.id for config in load_vehicle_configurations()}
    assert {key: labels for key, labels in families.items() if len(labels) > 1} == {}


def test_each_gearbox_names_the_axle_its_final_drive_belongs_to() -> None:
    """The saved final drive is the driven axle's; AWD rows say which when the data does.

    An AWD row with one published axle ratio stores it in the rear field without
    saying which axle it is, so no axle is claimed. A front-only ratio on an AWD
    row is an e-AWD hybrid whose engine drives the front axle.
    """
    axles: dict[tuple[str, str | None], set[str]] = {}
    for entry in load_car_library():
        for variant in entry["variants"]:
            configs = get_exact_configurations_for_variant(
                entry["brand"], entry["type"], entry["model"], variant["name"]
            )
            for gearbox, config in zip(variant["gearboxes"], configs, strict=True):
                both = config.final_drive_front is not None and config.final_drive_rear is not None
                kind = "both" if both else "front" if config.final_drive_front else "rear"
                if gearbox["final_drive_ratio"] is None:
                    kind = "none"
                axles.setdefault(
                    (variant["drivetrain"], gearbox.get("final_drive_axle")), set()
                ).add(kind)
    assert axles == {
        ("FWD", "front"): {"front"},
        ("FWD", None): {"none"},
        ("RWD", "rear"): {"rear"},
        ("RWD", None): {"none"},
        ("AWD", "rear"): {"both"},
        ("AWD", "front"): {"front"},
        ("AWD", None): {"rear", "none"},
    }
    picked = get_models_for_brand_type("BMW", "Hatchback")
    e_awd = next(
        variant
        for entry in picked
        if entry["model"].startswith("2 Series Active Tourer (F45")
        for variant in entry["variants"]
        if variant["name"] == "225xe"
    )
    assert [(g["fuel_type"], g.get("final_drive_axle")) for g in e_awd["gearboxes"]] == [
        ("PHEV", "front")
    ]
