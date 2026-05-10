"""Powertrain, gearbox, drivetrain, and final-drive validation rules."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import VehicleConfiguration

from ._car_library_validation_common import (
    AWD_BADGE_TOKENS,
    FINAL_DRIVE_RANGE,
    GEAR_RATIO_RANGE,
    RWD_BADGE_TOKENS,
    TOP_GEAR_RANGE,
    CarLibraryValidationIssue,
    classify_fuel_type,
    float_or_none,
    in_range,
    is_single_speed_gearbox,
    text,
)


def validate_gearboxes(
    gearboxes: object,
    *,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    if not isinstance(gearboxes, list):
        return
    for gearbox in gearboxes:
        if not isinstance(gearbox, Mapping):
            continue
        validate_single_gearbox(
            text(gearbox.get("name")),
            final_drive_ratio=gearbox.get("final_drive_ratio"),
            top_gear_ratio=gearbox.get("top_gear_ratio"),
            gear_ratios=gearbox.get("gear_ratios"),
            entity=entity,
            label=label,
            issues=issues,
        )


def validate_single_gearbox(
    gearbox_name: str,
    *,
    final_drive_ratio: object,
    top_gear_ratio: object,
    gear_ratios: object,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    final_drive = float_or_none(final_drive_ratio)
    if final_drive is not None and not in_range(final_drive, FINAL_DRIVE_RANGE):
        issues.append(
            CarLibraryValidationIssue(
                rule="final_drive_ratio_range",
                entity=entity,
                message=(
                    f"{label} gearbox {gearbox_name!r} has implausible "
                    f"final_drive_ratio={final_drive}"
                ),
            )
        )
    top_gear = float_or_none(top_gear_ratio)
    if top_gear is not None and not in_range(top_gear, TOP_GEAR_RANGE):
        issues.append(
            CarLibraryValidationIssue(
                rule="top_gear_ratio_range",
                entity=entity,
                message=(
                    f"{label} gearbox {gearbox_name!r} has implausible top_gear_ratio={top_gear}"
                ),
            )
        )
    if not isinstance(gear_ratios, list):
        return
    parsed_ratios = [float_or_none(value) for value in gear_ratios]
    if any(value is None or not in_range(value, GEAR_RATIO_RANGE) for value in parsed_ratios):
        issues.append(
            CarLibraryValidationIssue(
                rule="gear_ratio_range",
                entity=entity,
                message=(
                    f"{label} gearbox {gearbox_name!r} has implausible gear_ratios={gear_ratios!r}"
                ),
            )
        )
        return
    ratios = [value for value in parsed_ratios if value is not None]
    if any(
        next_ratio >= current_ratio
        for current_ratio, next_ratio in zip(ratios, ratios[1:], strict=False)
    ):
        issues.append(
            CarLibraryValidationIssue(
                rule="gear_ratio_order",
                entity=entity,
                message=f"{label} gearbox {gearbox_name!r} must keep descending gear ratios",
            )
        )


def validate_drivetrain_badges(
    variant_name: str,
    *,
    drivetrain: str,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    normalized_name = variant_name.lower()
    if any(token in normalized_name for token in AWD_BADGE_TOKENS) and drivetrain != "AWD":
        issues.append(
            CarLibraryValidationIssue(
                rule="badge_requires_awd",
                entity=entity,
                message=(
                    f"{label} uses an AWD badge in the variant name but drivetrain={drivetrain!r}"
                ),
            )
        )
    if any(token in normalized_name for token in RWD_BADGE_TOKENS) and drivetrain != "RWD":
        issues.append(
            CarLibraryValidationIssue(
                rule="edrive_requires_rwd",
                entity=entity,
                message=(
                    f"{label} uses an eDrive badge in the variant name "
                    f"but drivetrain={drivetrain!r}"
                ),
            )
        )


def validate_powertrain_gearbox_consistency(
    *,
    engine_name: str | None,
    gearboxes: object,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    if not isinstance(gearboxes, list):
        return
    fuel_type = classify_fuel_type(engine_name)
    for gearbox in gearboxes:
        if not isinstance(gearbox, Mapping):
            continue
        gearbox_name = text(gearbox.get("name"))
        is_single_speed = is_single_speed_gearbox(gearbox_name)
        if fuel_type == "EV" and not is_single_speed:
            issues.append(
                CarLibraryValidationIssue(
                    rule="pure_ev_requires_single_speed",
                    entity=entity,
                    message=f"{label} is EV but gearbox {gearbox_name!r} is not single-speed",
                )
            )
        if fuel_type == "ICE" and is_single_speed:
            issues.append(
                CarLibraryValidationIssue(
                    rule="ice_must_not_use_single_speed",
                    entity=entity,
                    message=f"{label} is ICE but gearbox {gearbox_name!r} is single-speed",
                )
            )


def validate_manual_or_automatic_claims(
    *,
    variant_name: str,
    gearboxes: object,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    if not isinstance(gearboxes, list):
        return
    normalized_name = variant_name.lower()
    gearbox_names = [
        text(gearbox.get("name")).lower() for gearbox in gearboxes if isinstance(gearbox, Mapping)
    ]
    if "manual" in normalized_name and not any("manual" in name for name in gearbox_names):
        issues.append(
            CarLibraryValidationIssue(
                rule="manual_claim_mismatch",
                entity=entity,
                message=f"{label} claims manual in the variant name but exposes no manual gearbox",
            )
        )
    claims_automatic = any(
        token in normalized_name for token in ("automatic", "steptronic", "dkg", "s tronic")
    )
    if claims_automatic and any("manual" in name for name in gearbox_names):
        issues.append(
            CarLibraryValidationIssue(
                rule="automatic_claim_mismatch",
                entity=entity,
                message=f"{label} claims automatic transmission but still exposes a manual gearbox",
            )
        )


def validate_final_drive_layout(
    config: VehicleConfiguration,
    *,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    if config.drivetrain == "FWD" and config.final_drive_rear is not None:
        issues.append(
            CarLibraryValidationIssue(
                rule="drivetrain_final_drive_layout",
                entity=entity,
                message=f"{label} is FWD but still sets final_drive_rear",
            )
        )
    if config.drivetrain == "RWD" and config.final_drive_front is not None:
        issues.append(
            CarLibraryValidationIssue(
                rule="drivetrain_final_drive_layout",
                entity=entity,
                message=f"{label} is RWD but still sets final_drive_front",
            )
        )
    if config.driven_final_drive_ratio is None and (
        config.order_analysis_policy.usable_for_driveshaft_order
        or config.order_analysis_policy.usable_for_wheel_order
        or not config.order_analysis_policy.requires_manual_confirmation
    ):
        issues.append(
            CarLibraryValidationIssue(
                rule="drivetrain_final_drive_layout",
                entity=entity,
                message=f"{label} does not expose any driven final-drive ratio",
            )
        )
