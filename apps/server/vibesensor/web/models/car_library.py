"""Car-library HTTP API models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from vibesensor.web.models.base import _StrictBase


class CarLibraryBrandsResponse(BaseModel):
    """Response body listing available car manufacturer brands."""

    brands: list[str]


class CarLibraryTypesResponse(BaseModel):
    """Response body listing available car body types."""

    types: list[str]


class CarLibraryGearboxEntry(_StrictBase):
    """A gearbox option from the car library (gear ratios)."""

    name: str = Field(min_length=1)
    final_drive_ratio: float | None = Field(
        gt=0, description="`null` when the library has no final drive for this gearbox."
    )
    top_gear_ratio: float | None = Field(
        gt=0, description="`null` when the library has no top gear for this gearbox."
    )
    fuel_type: Literal["ICE", "PHEV", "EV"]
    final_drive_axle: Literal["front", "rear"] | None = Field(
        default=None,
        description=(
            "The axle the final drive belongs to; `null` when the library row doesn't say "
            "(an all-wheel-drive row with one published axle ratio)."
        ),
    )
    gear_ratios: list[float] | None = Field(default=None, min_length=1)
    source_status: Literal["exact_row"] | None = None
    final_drive_ratio_confidence: str | None = None
    top_gear_ratio_confidence: str | None = None
    gear_ratios_confidence: str | None = None
    transmission_confidence: str | None = None
    requires_manual_confirmation: bool | None = None


class CarLibraryTireDimensionsEntry(_StrictBase):
    """One axle's tire dimensions."""

    width_mm: float = Field(gt=0)
    aspect_pct: float = Field(gt=0)
    rim_in: float = Field(gt=0)


class CarLibraryTireOptionEntry(_StrictBase):
    """A tire size option from the car library."""

    name: str = Field(min_length=1)
    tire_width_mm: float = Field(gt=0)
    tire_aspect_pct: float = Field(gt=0)
    rim_in: float = Field(gt=0)
    front: CarLibraryTireDimensionsEntry
    rear: CarLibraryTireDimensionsEntry | None = None
    default_axle_for_speed: Literal["front", "rear", "average"] = "rear"
    source_confidence: str | None = None


class CarLibraryEngineProfileEntry(_StrictBase):
    """The engine's layout and cylinder count, read from the library's engine text."""

    layout: Literal["inline", "v", "flat", "w", "rotary"]
    cylinders: int = Field(ge=1)


class CarLibraryVariantEntry(_StrictBase):
    """A specific variant/trim of a car library model entry.

    A variant whose rows differ only by model year is split into one entry
    per model-year period, named with its years (``"xDrive25d (2021–2022)"``).
    """

    name: str = Field(min_length=1)
    engine: str | None = None
    engine_profile: CarLibraryEngineProfileEntry | None = Field(
        default=None,
        description="`null` for an EV, or when the variant's rows name different engines.",
    )
    drivetrain: Literal["FWD", "RWD", "AWD"]
    gearboxes: list[CarLibraryGearboxEntry] | None = None
    tire_options: list[CarLibraryTireOptionEntry] | None = None
    tire_width_mm: float | None = Field(default=None, gt=0)
    tire_aspect_pct: float | None = Field(default=None, gt=0)
    rim_in: float | None = Field(default=None, gt=0)
    production_start_year: int | None = Field(
        default=None, description="First model year of the variant's rows."
    )
    production_end_year: int | None = Field(
        default=None, description="Last model year of the variant's rows."
    )


class CarLibraryModelEntry(_StrictBase):
    """A full car library entry with brand, model, tire options, and variants.

    One entry per model generation; ``model`` names the generation code and
    its model years, e.g. ``"X1 (F48, 2015–2022)"``.
    """

    brand: str
    type: str
    model: str
    gearboxes: list[CarLibraryGearboxEntry]
    tire_options: list[CarLibraryTireOptionEntry] = Field(min_length=1)
    tire_width_mm: float = Field(gt=0)
    tire_aspect_pct: float = Field(gt=0)
    rim_in: float = Field(gt=0)
    variants: list[CarLibraryVariantEntry] = Field(default_factory=list)


class CarLibraryModelsResponse(BaseModel):
    """Response body listing car library model entries."""

    models: list[CarLibraryModelEntry]
