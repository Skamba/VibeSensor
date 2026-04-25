"""Exact vehicle configuration rows for drivetrain and order-analysis reference data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .tire_spec import TireSpec

__all__ = [
    "VehicleConfiguration",
    "VehicleConfigurationTireOption",
    "VehicleConfigurationSourceStatus",
    "VehicleDrivetrain",
    "VehicleFuelType",
]

VehicleFuelType = Literal["ICE", "PHEV", "EV"]
VehicleDrivetrain = Literal["FWD", "RWD", "AWD"]
VehicleConfigurationSourceStatus = Literal["exact_row", "compat_projection"]


@dataclass(frozen=True, slots=True)
class VehicleConfigurationTireOption:
    """Named tire option attached to one exact or projected vehicle configuration."""

    name: str
    spec: TireSpec


@dataclass(frozen=True, slots=True)
class VehicleConfiguration:
    """One typed drivetrain configuration row used as order-analysis source data."""

    brand: str
    car_type: str
    model_name: str
    variant_name: str
    drivetrain: VehicleDrivetrain
    transmission_name: str
    top_gear_ratio: float
    default_tire: TireSpec
    tire_options: tuple[VehicleConfigurationTireOption, ...]
    fuel_type: VehicleFuelType = "ICE"
    market: str | None = None
    model_code: str | None = None
    body_code: str | None = None
    production_start_year: int | None = None
    production_end_year: int | None = None
    engine_code: str | None = None
    engine_name: str | None = None
    transmission_code: str | None = None
    gear_ratios: tuple[float, ...] | None = None
    final_drive_front: float | None = None
    final_drive_rear: float | None = None
    transfer_case_ratio: float | None = None
    source_status: VehicleConfigurationSourceStatus = "exact_row"

    @property
    def driven_final_drive_ratio(self) -> float | None:
        """Return the most relevant driven final-drive ratio for the configuration."""

        if self.drivetrain == "FWD":
            return self.final_drive_front
        if self.drivetrain == "RWD":
            return self.final_drive_rear
        if self.final_drive_rear is not None:
            return self.final_drive_rear
        return self.final_drive_front
