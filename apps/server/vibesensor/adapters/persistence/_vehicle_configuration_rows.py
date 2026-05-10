"""Typed row schema and domain projection for vehicle configuration shards."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict, cast

from pydantic import ConfigDict, TypeAdapter

from vibesensor.domain import (
    AxleTireSetup,
    TireSpec,
    VehicleConfiguration,
    VehicleConfigurationConfidence,
    VehicleConfigurationIssue,
    VehicleConfigurationNote,
    VehicleConfigurationTireOption,
    VehicleDrivetrain,
    VehicleFieldConfidence,
    VehicleFieldMetadata,
    VehicleFuelType,
    VehicleOrderAnalysisPolicyOverride,
    apply_order_analysis_policy_override,
    derive_order_analysis_policy,
)

_STRICT_TYPEDDICT_CONFIG = ConfigDict(extra="forbid")


class VehicleFieldMetadataRow(TypedDict):
    confidence: VehicleFieldConfidence
    evidence_refs: NotRequired[list[str]]
    verified_at: NotRequired[str]
    notes: NotRequired[str]


class VehicleDrivetrainRow(VehicleFieldMetadataRow):
    value: VehicleDrivetrain


class VehicleTransmissionRow(VehicleFieldMetadataRow):
    name: str
    code: NotRequired[str]


class VehicleNumericFieldRow(VehicleFieldMetadataRow):
    value: float


class VehicleNumericSequenceFieldRow(VehicleFieldMetadataRow):
    value: list[float]


class VehicleTireDimensionsRow(TypedDict):
    width_mm: float
    aspect_pct: float
    rim_in: float


class VehicleTireSetupRow(VehicleFieldMetadataRow):
    front: VehicleTireDimensionsRow
    rear: NotRequired[VehicleTireDimensionsRow]
    default_axle_for_speed: NotRequired[Literal["front", "rear", "average"]]


class VehicleTireOptionRow(VehicleTireSetupRow):
    name: str


class VehicleTiresRow(TypedDict):
    default: VehicleTireSetupRow
    options: NotRequired[list[VehicleTireOptionRow]]


class VehicleRatiosRow(TypedDict):
    top_gear_ratio: VehicleNumericFieldRow
    gear_ratios: NotRequired[VehicleNumericSequenceFieldRow]
    final_drive_front: NotRequired[VehicleNumericFieldRow]
    final_drive_rear: NotRequired[VehicleNumericFieldRow]
    transfer_case_ratio: NotRequired[VehicleNumericFieldRow]


class VehicleConfigurationNoteRow(TypedDict):
    note: str
    evidence_refs: NotRequired[list[str]]


class VehicleConfigurationIssueRow(TypedDict):
    item: str
    reason: str
    evidence_refs: NotRequired[list[str]]


class VehicleOrderAnalysisPolicyOverrideRow(TypedDict):
    reason: str
    usable_for_engine_order: NotRequired[bool]
    usable_for_driveshaft_order: NotRequired[bool]
    usable_for_wheel_order: NotRequired[bool]
    requires_manual_confirmation: NotRequired[bool]


class VehicleConfigurationRow(TypedDict):
    id: str
    brand: str
    type: str
    model_name: str
    variant_name: str
    fuel_type: VehicleFuelType
    drivetrain: VehicleDrivetrainRow
    transmission: VehicleTransmissionRow
    ratios: VehicleRatiosRow
    tires: VehicleTiresRow
    configuration_confidence: VehicleConfigurationConfidence
    market: NotRequired[str]
    model_code: NotRequired[str]
    body_code: NotRequired[str]
    production_start_year: NotRequired[int]
    production_end_year: NotRequired[int]
    engine_code: NotRequired[str]
    engine_name: NotRequired[str]
    verification_notes: NotRequired[list[VehicleConfigurationNoteRow]]
    unresolved: NotRequired[list[VehicleConfigurationIssueRow]]
    order_analysis_policy_override: NotRequired[VehicleOrderAnalysisPolicyOverrideRow]


for _typed_dict in (
    VehicleConfigurationIssueRow,
    VehicleConfigurationNoteRow,
    VehicleConfigurationRow,
    VehicleDrivetrainRow,
    VehicleFieldMetadataRow,
    VehicleNumericFieldRow,
    VehicleNumericSequenceFieldRow,
    VehicleOrderAnalysisPolicyOverrideRow,
    VehicleRatiosRow,
    VehicleTireDimensionsRow,
    VehicleTireOptionRow,
    VehicleTireSetupRow,
    VehicleTiresRow,
    VehicleTransmissionRow,
):
    cast(Any, _typed_dict).__pydantic_config__ = _STRICT_TYPEDDICT_CONFIG

_VEHICLE_CONFIGURATION_ADAPTER = TypeAdapter(list[VehicleConfigurationRow])


def validate_vehicle_configuration_rows(payload: object) -> list[VehicleConfigurationRow]:
    """Validate expanded shard rows against the strict typed row contract."""

    return _VEHICLE_CONFIGURATION_ADAPTER.validate_python(payload)


def vehicle_configuration_from_row(row: VehicleConfigurationRow) -> VehicleConfiguration:
    """Project one validated row into the domain vehicle configuration."""

    ratios = row["ratios"]
    default_tire_setup = _tire_setup_from_row(row["tires"]["default"])
    drivetrain_value = row["drivetrain"]["value"]
    final_drive_front = (
        ratios["final_drive_front"]["value"] if "final_drive_front" in ratios else None
    )
    final_drive_rear = ratios["final_drive_rear"]["value"] if "final_drive_rear" in ratios else None
    derived_policy = derive_order_analysis_policy(
        top_gear_ratio=ratios["top_gear_ratio"]["value"],
        final_drive_front=final_drive_front,
        final_drive_rear=final_drive_rear,
        drivetrain=drivetrain_value,
    )
    override_row = row.get("order_analysis_policy_override")
    override = (
        VehicleOrderAnalysisPolicyOverride(
            reason=override_row["reason"],
            usable_for_engine_order=override_row.get("usable_for_engine_order"),
            usable_for_driveshaft_order=override_row.get("usable_for_driveshaft_order"),
            usable_for_wheel_order=override_row.get("usable_for_wheel_order"),
            requires_manual_confirmation=override_row.get("requires_manual_confirmation"),
        )
        if override_row is not None
        else None
    )
    final_policy = apply_order_analysis_policy_override(derived_policy, override)
    return VehicleConfiguration(
        id=row["id"],
        brand=row["brand"],
        car_type=row["type"],
        market=row.get("market"),
        model_code=row.get("model_code"),
        body_code=row.get("body_code"),
        production_start_year=row.get("production_start_year"),
        production_end_year=row.get("production_end_year"),
        model_name=row["model_name"],
        variant_name=row["variant_name"],
        engine_code=row.get("engine_code"),
        engine_name=row.get("engine_name"),
        fuel_type=row["fuel_type"],
        drivetrain=drivetrain_value,
        drivetrain_metadata=_metadata_from_row(row["drivetrain"]),
        transmission_code=row["transmission"].get("code"),
        transmission_name=row["transmission"]["name"],
        transmission_metadata=_metadata_from_row(row["transmission"]),
        top_gear_ratio=ratios["top_gear_ratio"]["value"],
        top_gear_ratio_metadata=_metadata_from_row(ratios["top_gear_ratio"]),
        gear_ratios=(tuple(ratios["gear_ratios"]["value"]) if "gear_ratios" in ratios else None),
        gear_ratios_metadata=(
            _metadata_from_row(ratios["gear_ratios"]) if "gear_ratios" in ratios else None
        ),
        final_drive_front=final_drive_front,
        final_drive_front_metadata=(
            _metadata_from_row(ratios["final_drive_front"])
            if "final_drive_front" in ratios
            else None
        ),
        final_drive_rear=final_drive_rear,
        final_drive_rear_metadata=(
            _metadata_from_row(ratios["final_drive_rear"]) if "final_drive_rear" in ratios else None
        ),
        transfer_case_ratio=(
            ratios["transfer_case_ratio"]["value"] if "transfer_case_ratio" in ratios else None
        ),
        default_tire=default_tire_setup.boundary_tire_spec,
        tire_options=tuple(
            _tire_option_from_row(option) for option in row["tires"].get("options", [])
        ),
        tire_metadata=_metadata_from_row(row["tires"]["default"]),
        configuration_confidence=row["configuration_confidence"],
        order_analysis_policy=final_policy,
        verification_notes=tuple(
            VehicleConfigurationNote(
                note=note["note"],
                evidence_refs=tuple(note.get("evidence_refs", [])),
            )
            for note in row.get("verification_notes", [])
        ),
        unresolved=tuple(
            VehicleConfigurationIssue(
                item=issue["item"],
                reason=issue["reason"],
                evidence_refs=tuple(issue.get("evidence_refs", [])),
            )
            for issue in row.get("unresolved", [])
        ),
    )


def _metadata_from_row(row: VehicleFieldMetadataRow) -> VehicleFieldMetadata:
    return VehicleFieldMetadata(
        confidence=row["confidence"],
        evidence_refs=tuple(row.get("evidence_refs", [])),
        verified_at=row.get("verified_at"),
        notes=row.get("notes"),
    )


def _tire_spec_from_dimensions_row(row: VehicleTireDimensionsRow) -> TireSpec:
    return TireSpec(
        width_mm=float(row["width_mm"]),
        aspect_pct=float(row["aspect_pct"]),
        rim_in=float(row["rim_in"]),
    )


def _tire_setup_from_row(row: VehicleTireSetupRow) -> AxleTireSetup:
    front = _tire_spec_from_dimensions_row(row["front"])
    rear = _tire_spec_from_dimensions_row(row["rear"]) if "rear" in row else front
    default_axle_for_speed = row.get("default_axle_for_speed")
    if default_axle_for_speed not in {"front", "rear", "average"}:
        default_axle_for_speed = "rear"
    return AxleTireSetup(
        front=front,
        rear=rear,
        default_axle_for_speed=default_axle_for_speed,
        source_confidence=row["confidence"],
    )


def _tire_option_from_row(row: VehicleTireOptionRow) -> VehicleConfigurationTireOption:
    return VehicleConfigurationTireOption(
        name=row["name"],
        tire_setup=_tire_setup_from_row(row),
        metadata=_metadata_from_row(row),
    )
