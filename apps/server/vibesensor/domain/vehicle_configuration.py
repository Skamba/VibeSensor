"""Exact vehicle-configuration rows used as canonical order-analysis source data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .tire_spec import AxleTireSetup, TireSpec

__all__ = [
    "VehicleConfiguration",
    "VehicleConfigurationConfidence",
    "VehicleConfigurationField",
    "VehicleConfigurationIssue",
    "VehicleConfigurationNote",
    "VehicleConfigurationSourceStatus",
    "VehicleConfigurationTireOption",
    "VehicleCoverageClassification",
    "VehicleDrivetrain",
    "VehicleFieldConfidence",
    "VehicleFieldMetadata",
    "VehicleFuelType",
    "VehicleOrderAnalysisPolicy",
]

VehicleFuelType = Literal["ICE", "PHEV", "EV"]
VehicleDrivetrain = Literal["FWD", "RWD", "AWD"]
VehicleConfigurationSourceStatus = Literal["exact_row"]
VehicleConfigurationConfidence = Literal[
    "high_confidence",
    "medium_confidence",
    "low_confidence",
    "no_confidence",
    "not_applicable",
]
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
VehicleCoverageClassification = Literal["trusted", "approximate", "backlog_unverified"]


@dataclass(frozen=True, slots=True)
class VehicleFieldMetadata:
    """Confidence and evidence metadata for one canonical vehicle field."""

    confidence: VehicleFieldConfidence
    evidence_refs: tuple[str, ...] = ()
    verified_at: str | None = None
    notes: str | None = None

    @property
    def requires_evidence_refs(self) -> bool:
        """Whether this confidence level must resolve to explicit evidence."""

        return self.confidence in {
            "official_exact",
            "official_derived",
            "reputable_secondary_crosschecked",
        }


@dataclass(frozen=True, slots=True)
class VehicleConfigurationNote:
    """A preserved verification note that is not itself runtime truth."""

    note: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VehicleConfigurationIssue:
    """One unresolved research item attached to a canonical configuration row."""

    item: str
    reason: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VehicleOrderAnalysisPolicy:
    """Policy flags derived from canonical car-data confidence."""

    usable_for_engine_order: bool
    usable_for_driveshaft_order: bool
    usable_for_wheel_order: bool
    requires_manual_confirmation: bool


@dataclass(frozen=True, slots=True)
class VehicleConfigurationTireOption:
    """Named tire option attached to one canonical vehicle configuration."""

    name: str
    tire_setup: AxleTireSetup
    metadata: VehicleFieldMetadata | None = None


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
    id: str | None = None
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
    drivetrain_metadata: VehicleFieldMetadata | None = None
    transmission_metadata: VehicleFieldMetadata | None = None
    top_gear_ratio_metadata: VehicleFieldMetadata | None = None
    gear_ratios_metadata: VehicleFieldMetadata | None = None
    final_drive_front_metadata: VehicleFieldMetadata | None = None
    final_drive_rear_metadata: VehicleFieldMetadata | None = None
    tire_metadata: VehicleFieldMetadata | None = None
    configuration_confidence: VehicleConfigurationConfidence = "not_applicable"
    order_analysis_policy: VehicleOrderAnalysisPolicy = field(
        default_factory=lambda: VehicleOrderAnalysisPolicy(
            usable_for_engine_order=False,
            usable_for_driveshaft_order=False,
            usable_for_wheel_order=False,
            requires_manual_confirmation=True,
        )
    )
    verification_notes: tuple[VehicleConfigurationNote, ...] = ()
    unresolved: tuple[VehicleConfigurationIssue, ...] = ()

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

    def metadata_for(
        self,
        field_name: VehicleConfigurationField,
    ) -> VehicleFieldMetadata | None:
        """Return canonical metadata for *field_name* when present."""

        mapping: dict[VehicleConfigurationField, VehicleFieldMetadata | None] = {
            "drivetrain": self.drivetrain_metadata,
            "final_drive_front": self.final_drive_front_metadata,
            "final_drive_rear": self.final_drive_rear_metadata,
            "gear_ratios": self.gear_ratios_metadata,
            "tire_dimensions": self.tire_metadata,
            "top_gear_ratio": self.top_gear_ratio_metadata,
            "transmission_name": self.transmission_metadata,
        }
        return mapping[field_name]

    def order_reference_confidence(
        self,
        field_name: Literal["current_gear_ratio", "final_drive_ratio", "transmission_name"],
    ) -> VehicleFieldConfidence:
        """Return machine-readable confidence for one order-reference field."""

        if field_name == "current_gear_ratio":
            entry = self.metadata_for("top_gear_ratio")
        elif field_name == "transmission_name":
            entry = self.metadata_for("transmission_name")
        elif self.drivetrain == "FWD":
            entry = self.metadata_for("final_drive_front")
        elif self.drivetrain == "RWD":
            entry = self.metadata_for("final_drive_rear")
        else:
            entry = self.metadata_for("final_drive_rear") or self.metadata_for("final_drive_front")
        if entry is not None:
            return entry.confidence
        return "unverified"

    @property
    def coverage_policy_fields(self) -> tuple[VehicleConfigurationField, ...]:
        """Return the minimum field set required to trust this config for order analysis."""

        fields: list[VehicleConfigurationField] = [
            "drivetrain",
            "tire_dimensions",
            "transmission_name",
            "top_gear_ratio",
        ]
        if self.final_drive_front is not None:
            fields.append("final_drive_front")
        if self.final_drive_rear is not None:
            fields.append("final_drive_rear")
        return tuple(fields)

    def coverage_policy_confidence(
        self,
        field_name: VehicleConfigurationField,
    ) -> VehicleFieldConfidence:
        """Return the policy-driving confidence for one order-analysis-critical field."""

        if field_name == "top_gear_ratio":
            return self.order_reference_confidence("current_gear_ratio")
        if field_name == "transmission_name":
            return self.order_reference_confidence("transmission_name")
        if field_name in {"final_drive_front", "final_drive_rear"}:
            entry = self.metadata_for(field_name)
            return entry.confidence if entry is not None else "unverified"
        entry = self.metadata_for(field_name)
        return entry.confidence if entry is not None else "unverified"

    @property
    def coverage_policy_classification(self) -> VehicleCoverageClassification:
        """Classify whether this config is trusted, approximate, or backlog-grade."""

        confidences = tuple(
            self.coverage_policy_confidence(field_name)
            for field_name in self.coverage_policy_fields
        )
        if any(confidence == "unverified" for confidence in confidences):
            return "backlog_unverified"
        if any(confidence == "family_default" for confidence in confidences):
            return "approximate"
        return "trusted"

    @property
    def requires_manual_drivetrain_confirmation(self) -> bool:
        """Whether selected drivetrain ratios should be treated as approximate."""

        return self.order_analysis_policy.requires_manual_confirmation
