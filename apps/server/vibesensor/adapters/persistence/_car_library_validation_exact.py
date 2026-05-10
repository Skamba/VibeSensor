"""Validation flow for canonical exact vehicle configuration rows."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import VehicleConfiguration, VehicleConfigurationField

from ._car_library_validation_common import (
    CarLibraryValidationIssue,
    variant_entity,
    vehicle_configuration_fuzzy_label_key,
    vehicle_configuration_identity_key,
)
from ._car_library_validation_powertrain import (
    validate_drivetrain_badges,
    validate_final_drive_layout,
    validate_powertrain_gearbox_consistency,
    validate_single_gearbox,
)
from ._car_library_validation_tires import validate_tire_setup, validate_tire_spec


def validate_vehicle_configuration(
    config: VehicleConfiguration,
    issues: list[CarLibraryValidationIssue],
) -> None:
    entity = variant_entity(config.brand, config.model_name, config.variant_name)
    label = f"{config.brand} {config.model_name} / {config.variant_name}".strip(" /")

    validate_drivetrain_badges(
        config.variant_name,
        drivetrain=config.drivetrain,
        entity=entity,
        label=label,
        issues=issues,
    )
    validate_single_gearbox(
        config.transmission_name,
        final_drive_ratio=config.driven_final_drive_ratio,
        top_gear_ratio=config.top_gear_ratio,
        gear_ratios=config.gear_ratios,
        entity=entity,
        label=label,
        issues=issues,
    )
    validate_powertrain_gearbox_consistency(
        engine_name=config.engine_name,
        gearboxes=[
            {
                "name": config.transmission_name,
                "top_gear_ratio": config.top_gear_ratio,
            }
        ],
        entity=entity,
        label=label,
        issues=issues,
    )
    validate_final_drive_layout(config, entity=entity, label=label, issues=issues)
    validate_tire_spec(
        config.default_tire,
        entity=entity,
        label=f"{label} default tire",
        issues=issues,
    )
    for option in config.tire_options:
        validate_tire_setup(
            option.tire_setup,
            entity=entity,
            label=f"{label} / {option.name}",
            issues=issues,
        )
    validate_exact_row_metadata(config, entity=entity, label=label, issues=issues)


def validate_exact_row_metadata(
    config: VehicleConfiguration,
    *,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    required_fields: set[VehicleConfigurationField] = {
        "top_gear_ratio",
        "transmission_name",
        "drivetrain",
        "tire_dimensions",
    }
    if config.final_drive_front is not None:
        required_fields.add("final_drive_front")
    if config.final_drive_rear is not None:
        required_fields.add("final_drive_rear")
    if config.gear_ratios is not None:
        required_fields.add("gear_ratios")
    missing = sorted(field for field in required_fields if config.metadata_for(field) is None)
    if missing:
        issues.append(
            CarLibraryValidationIssue(
                rule="missing_field_metadata",
                entity=entity,
                message=f"{label} exact row is missing canonical metadata for {', '.join(missing)}",
            )
        )


def validate_vehicle_configuration_duplicates(
    configs: Sequence[VehicleConfiguration],
    issues: list[CarLibraryValidationIssue],
) -> None:
    by_identity: dict[tuple[object, ...], list[VehicleConfiguration]] = {}
    by_fuzzy_label: dict[tuple[str, str, str], list[VehicleConfiguration]] = {}
    for config in configs:
        if not config.id:
            continue
        by_identity.setdefault(vehicle_configuration_identity_key(config), []).append(config)
        by_fuzzy_label.setdefault(vehicle_configuration_fuzzy_label_key(config), []).append(config)

    for group in by_identity.values():
        if len(group) <= 1:
            continue
        peers = sorted(str(other.id) for other in group)
        for config in group:
            row_id = str(config.id)
            others = [pid for pid in peers if pid != row_id]
            issues.append(
                CarLibraryValidationIssue(
                    rule="duplicate_vehicle_configuration",
                    entity=row_id,
                    message=(
                        f"{config.brand} {config.model_name} / {config.variant_name} "
                        f"shares normalized identity with {', '.join(others)}"
                    ),
                )
            )

    for group in by_fuzzy_label.values():
        if len(group) <= 1:
            continue
        identity_keys = {vehicle_configuration_identity_key(c) for c in group}
        if len(identity_keys) <= 1:
            continue
        raw_labels = {(c.brand, c.model_name, c.variant_name) for c in group}
        if len(raw_labels) <= 1:
            continue
        peers = sorted(str(other.id) for other in group)
        for config in group:
            row_id = str(config.id)
            others = [pid for pid in peers if pid != row_id]
            issues.append(
                CarLibraryValidationIssue(
                    rule="near_duplicate_vehicle_configuration",
                    entity=row_id,
                    message=(
                        f"{config.brand} {config.model_name} / {config.variant_name} "
                        "matches another row after label normalization "
                        f"but has different math: {', '.join(others)}"
                    ),
                )
            )
