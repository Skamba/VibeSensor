"""Exact vehicle configuration rows for drivetrain and order-analysis reference data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .tire_spec import TireSpec

__all__ = [
    "VehicleConfigurationField",
    "VehicleFieldConfidence",
    "VehicleFieldProvenance",
    "VehicleConfiguration",
    "VehicleConfigurationTireOption",
    "VehicleConfigurationSourceStatus",
    "VehicleDrivetrain",
    "VehicleFuelType",
]

VehicleFuelType = Literal["ICE", "PHEV", "EV"]
VehicleDrivetrain = Literal["FWD", "RWD", "AWD"]
VehicleConfigurationSourceStatus = Literal["exact_row", "compat_projection"]
VehicleFieldConfidence = Literal[
    "official_exact",
    "official_derived",
    "reputable_secondary_crosschecked",
    "family_default",
    "unverified",
    "user_confirmed",
]
VehicleConfigurationField = Literal[
    "final_drive_front",
    "final_drive_rear",
    "top_gear_ratio",
    "gear_ratios",
    "drivetrain",
    "tire_dimensions",
    "transmission_name",
]


@dataclass(frozen=True, slots=True)
class VehicleConfigurationTireOption:
    """Named tire option attached to one exact or projected vehicle configuration."""

    name: str
    spec: TireSpec


@dataclass(frozen=True, slots=True)
class VehicleFieldProvenance:
    """Machine-readable source and confidence metadata for one config field."""

    field_name: VehicleConfigurationField
    confidence: VehicleFieldConfidence
    source_id: str | None = None
    verified_at: str | None = None
    notes: str | None = None

    @property
    def requires_source_id(self) -> bool:
        """Whether this provenance entry must include a source identifier."""

        return self.confidence == "official_exact"


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
    field_provenance: tuple[VehicleFieldProvenance, ...] = ()

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

    def provenance_for(
        self,
        field_name: VehicleConfigurationField,
    ) -> VehicleFieldProvenance | None:
        """Return provenance metadata for *field_name* when present."""

        for entry in self.field_provenance:
            if entry.field_name == field_name:
                return entry
        return None

    def order_reference_confidence(
        self,
        field_name: Literal["current_gear_ratio", "final_drive_ratio", "transmission_name"],
    ) -> VehicleFieldConfidence:
        """Return machine-readable confidence for one order-reference field."""

        if field_name == "current_gear_ratio":
            entry = self.provenance_for("top_gear_ratio")
        elif field_name == "transmission_name":
            entry = self.provenance_for("transmission_name")
        elif self.drivetrain == "FWD":
            entry = self.provenance_for("final_drive_front")
        elif self.drivetrain == "RWD":
            entry = self.provenance_for("final_drive_rear")
        else:
            entry = self.provenance_for("final_drive_rear") or self.provenance_for(
                "final_drive_front"
            )
        if entry is not None:
            return entry.confidence
        if self.source_status == "compat_projection":
            return "family_default"
        return "unverified"

    @property
    def requires_manual_drivetrain_confirmation(self) -> bool:
        """Whether selected drivetrain ratios should be treated as approximate."""

        order_reference_fields: tuple[
            Literal["current_gear_ratio", "final_drive_ratio", "transmission_name"],
            ...,
        ] = ("current_gear_ratio", "final_drive_ratio", "transmission_name")
        return any(
            self.order_reference_confidence(field_name) in {"family_default", "unverified"}
            for field_name in order_reference_fields
        )
