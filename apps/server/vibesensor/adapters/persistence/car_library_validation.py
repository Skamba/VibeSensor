"""Physical plausibility and consistency validation for bundled car data."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from vibesensor.domain import (
    AxleTireSetup,
    TireSpec,
    VehicleConfiguration,
    VehicleConfigurationField,
)
from vibesensor.shared._data_files import resolve_static_data_file

__all__ = [
    "CarLibraryValidationIssue",
    "ensure_valid_car_library_rows",
    "ensure_valid_vehicle_configurations",
    "load_car_library_validation_allowlist",
    "validate_car_library_rows",
    "validate_vehicle_configurations",
]

_ALLOWLIST_FILE = resolve_static_data_file("car_library_validation_allowlist.json")
_AWD_BADGE_TOKENS = ("xdrive", "quattro", "4matic")
_RWD_BADGE_TOKENS = ("edrive",)
_FINAL_DRIVE_RANGE = (2.0, 15.0)
_TOP_GEAR_RANGE = (0.5, 1.1)
_GEAR_RATIO_RANGE = (0.4, 8.0)
_TIRE_DIAMETER_RANGE_MM = (550.0, 850.0)
_RIM_SUFFIX_RE = re.compile(r'(?P<rim>\d+)"$')


@dataclass(frozen=True, slots=True)
class _ResolvedTireSetup:
    front: TireSpec
    rear: TireSpec


@dataclass(frozen=True, slots=True)
class CarLibraryValidationIssue:
    """One machine-readable validation failure for bundled car data."""

    rule: str
    entity: str
    message: str


def load_car_library_validation_allowlist(
    path: Path = _ALLOWLIST_FILE,
) -> dict[tuple[str, str], str]:
    """Load the documented validation allowlist keyed by ``(rule, entity)``."""

    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"Could not load car-library validation allowlist from {path}: {exc}"
        ) from exc

    rows = payload.get("allowances")
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain an 'allowances' list")

    allowlist: dict[tuple[str, str], str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path} allowance #{index} must be an object")
        rule = row.get("rule")
        entity = row.get("entity")
        reason = row.get("reason")
        if not isinstance(rule, str) or not rule.strip():
            raise ValueError(f"{path} allowance #{index} missing non-empty rule")
        if not isinstance(entity, str) or not entity.strip():
            raise ValueError(f"{path} allowance #{index} missing non-empty entity")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path} allowance #{index} missing non-empty reason")
        key = (rule.strip(), entity.strip())
        if key in allowlist:
            raise ValueError(f"{path} duplicates allowance for rule={rule!r} entity={entity!r}")
        allowlist[key] = reason.strip()
    return allowlist


def ensure_valid_car_library_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    allowlist: Mapping[tuple[str, str], str] | None = None,
) -> None:
    """Raise ``ValueError`` when legacy car-library rows fail validation."""

    issues = validate_car_library_rows(rows, allowlist=allowlist)
    if issues:
        raise ValueError(_format_issue_summary("car library", issues))


def ensure_valid_vehicle_configurations(
    configs: Sequence[VehicleConfiguration],
    *,
    allowlist: Mapping[tuple[str, str], str] | None = None,
) -> None:
    """Raise ``ValueError`` when exact vehicle configuration rows fail validation."""

    issues = validate_vehicle_configurations(configs, allowlist=allowlist)
    if issues:
        raise ValueError(_format_issue_summary("vehicle configurations", issues))


def validate_car_library_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    allowlist: Mapping[tuple[str, str], str] | None = None,
) -> tuple[CarLibraryValidationIssue, ...]:
    """Return all validation issues for legacy ``car_library.json`` rows."""

    issues: list[CarLibraryValidationIssue] = []
    for entry in rows:
        _validate_legacy_entry(entry, issues)
    return _filter_allowlisted_issues(issues, allowlist)


def validate_vehicle_configurations(
    configs: Sequence[VehicleConfiguration],
    *,
    allowlist: Mapping[tuple[str, str], str] | None = None,
) -> tuple[CarLibraryValidationIssue, ...]:
    """Return all validation issues for exact vehicle configuration rows."""

    issues: list[CarLibraryValidationIssue] = []
    for config in configs:
        _validate_vehicle_configuration(config, issues)
    return _filter_allowlisted_issues(issues, allowlist)


def _validate_legacy_entry(
    entry: Mapping[str, object],
    issues: list[CarLibraryValidationIssue],
) -> None:
    brand = _text(entry.get("brand"))
    model = _text(entry.get("model"))
    entry_entity = _model_entity(brand, model)
    entry_label = f"{brand} {model}".strip()

    _validate_gearboxes(
        entry.get("gearboxes"),
        entity=entry_entity,
        label=entry_label,
        issues=issues,
    )
    _validate_default_tire(
        entity=entry_entity,
        label=f"{entry_label} default tire",
        width=entry.get("tire_width_mm"),
        aspect=entry.get("tire_aspect_pct"),
        rim=entry.get("rim_in"),
        issues=issues,
    )
    _validate_tire_options(
        entry.get("tire_options"),
        entity=entry_entity,
        label=entry_label,
        issues=issues,
    )

    variants = entry.get("variants")
    if not isinstance(variants, list):
        return

    seen_variants: set[str] = set()
    for variant in variants:
        if not isinstance(variant, Mapping):
            continue
        variant_name = _text(variant.get("name"))
        variant_entity = _variant_entity(brand, model, variant_name)
        variant_label = f"{entry_label} / {variant_name}".strip(" /")

        if variant_name in seen_variants:
            issues.append(
                CarLibraryValidationIssue(
                    rule="duplicate_variant_name",
                    entity=variant_entity,
                    message=f"{variant_label} duplicates a variant name within the same model",
                )
            )
        seen_variants.add(variant_name)

        _validate_drivetrain_badges(
            variant_name,
            drivetrain=_text(variant.get("drivetrain")),
            entity=variant_entity,
            label=variant_label,
            issues=issues,
        )
        variant_gearboxes = variant.get("gearboxes")
        effective_gearboxes = (
            variant_gearboxes if isinstance(variant_gearboxes, list) else entry.get("gearboxes")
        )
        if isinstance(variant_gearboxes, list):
            _validate_gearboxes(
                variant_gearboxes,
                entity=variant_entity,
                label=variant_label,
                issues=issues,
            )
        _validate_powertrain_gearbox_consistency(
            engine_name=_text(variant.get("engine")),
            gearboxes=effective_gearboxes,
            entity=variant_entity,
            label=variant_label,
            issues=issues,
        )
        _validate_manual_or_automatic_claims(
            variant_name=variant_name,
            gearboxes=effective_gearboxes,
            entity=variant_entity,
            label=variant_label,
            issues=issues,
        )
        if "tire_width_mm" in variant or "tire_aspect_pct" in variant or "rim_in" in variant:
            _validate_default_tire(
                entity=variant_entity,
                label=f"{variant_label} default tire",
                width=variant.get("tire_width_mm", entry.get("tire_width_mm")),
                aspect=variant.get("tire_aspect_pct", entry.get("tire_aspect_pct")),
                rim=variant.get("rim_in", entry.get("rim_in")),
                issues=issues,
            )
        if isinstance(variant.get("tire_options"), list):
            _validate_tire_options(
                variant.get("tire_options"),
                entity=variant_entity,
                label=variant_label,
                issues=issues,
            )


def _validate_vehicle_configuration(
    config: VehicleConfiguration,
    issues: list[CarLibraryValidationIssue],
) -> None:
    entity = _variant_entity(config.brand, config.model_name, config.variant_name)
    label = f"{config.brand} {config.model_name} / {config.variant_name}".strip(" /")

    _validate_drivetrain_badges(
        config.variant_name,
        drivetrain=config.drivetrain,
        entity=entity,
        label=label,
        issues=issues,
    )
    _validate_single_gearbox(
        config.transmission_name,
        final_drive_ratio=config.driven_final_drive_ratio,
        top_gear_ratio=config.top_gear_ratio,
        gear_ratios=config.gear_ratios,
        entity=entity,
        label=label,
        issues=issues,
    )
    _validate_powertrain_gearbox_consistency(
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
    _validate_final_drive_layout(config, entity=entity, label=label, issues=issues)
    _validate_tire_spec(
        config.default_tire,
        entity=entity,
        label=f"{label} default tire",
        issues=issues,
    )
    for option in config.tire_options:
        _validate_tire_setup(
            option.tire_setup,
            entity=entity,
            label=f"{label} / {option.name}",
            issues=issues,
        )
    if config.source_status == "exact_row":
        _validate_exact_row_provenance(config, entity=entity, label=label, issues=issues)


def _validate_gearboxes(
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
        _validate_single_gearbox(
            _text(gearbox.get("name")),
            final_drive_ratio=gearbox.get("final_drive_ratio"),
            top_gear_ratio=gearbox.get("top_gear_ratio"),
            gear_ratios=gearbox.get("gear_ratios"),
            entity=entity,
            label=label,
            issues=issues,
        )


def _validate_single_gearbox(
    gearbox_name: str,
    *,
    final_drive_ratio: object,
    top_gear_ratio: object,
    gear_ratios: object,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    final_drive = _float_or_none(final_drive_ratio)
    if final_drive is not None and not _in_range(final_drive, _FINAL_DRIVE_RANGE):
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
    top_gear = _float_or_none(top_gear_ratio)
    if top_gear is not None and not _in_range(top_gear, _TOP_GEAR_RANGE):
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
    parsed_ratios = [_float_or_none(value) for value in gear_ratios]
    if any(value is None or not _in_range(value, _GEAR_RATIO_RANGE) for value in parsed_ratios):
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


def _validate_drivetrain_badges(
    variant_name: str,
    *,
    drivetrain: str,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    normalized_name = variant_name.lower()
    if any(token in normalized_name for token in _AWD_BADGE_TOKENS) and drivetrain != "AWD":
        issues.append(
            CarLibraryValidationIssue(
                rule="badge_requires_awd",
                entity=entity,
                message=(
                    f"{label} uses an AWD badge in the variant name but drivetrain={drivetrain!r}"
                ),
            )
        )
    if any(token in normalized_name for token in _RWD_BADGE_TOKENS) and drivetrain != "RWD":
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


def _validate_powertrain_gearbox_consistency(
    *,
    engine_name: str | None,
    gearboxes: object,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    if not isinstance(gearboxes, list):
        return
    fuel_type = _classify_fuel_type(engine_name)
    for gearbox in gearboxes:
        if not isinstance(gearbox, Mapping):
            continue
        gearbox_name = _text(gearbox.get("name"))
        is_single_speed = _is_single_speed_gearbox(gearbox_name)
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


def _validate_manual_or_automatic_claims(
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
        _text(gearbox.get("name")).lower() for gearbox in gearboxes if isinstance(gearbox, Mapping)
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


def _validate_final_drive_layout(
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
    if config.driven_final_drive_ratio is None:
        issues.append(
            CarLibraryValidationIssue(
                rule="drivetrain_final_drive_layout",
                entity=entity,
                message=f"{label} does not expose any driven final-drive ratio",
            )
        )


def _validate_exact_row_provenance(
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
    missing = sorted(field for field in required_fields if config.provenance_for(field) is None)
    if missing:
        issues.append(
            CarLibraryValidationIssue(
                rule="missing_field_provenance",
                entity=entity,
                message=f"{label} exact row is missing field_provenance for {', '.join(missing)}",
            )
        )


def _validate_default_tire(
    *,
    entity: str,
    label: str,
    width: object,
    aspect: object,
    rim: object,
    issues: list[CarLibraryValidationIssue],
) -> None:
    spec = _tire_spec_from_values(width=width, aspect=aspect, rim=rim)
    if spec is None:
        issues.append(
            CarLibraryValidationIssue(
                rule="tire_dimensions_invalid",
                entity=entity,
                message=f"{label} does not expose usable tire dimensions",
            )
        )
        return
    _validate_tire_spec(spec, entity=entity, label=label, issues=issues)


def _validate_tire_options(
    options: object,
    *,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    if not isinstance(options, list):
        return
    for option in options:
        if not isinstance(option, Mapping):
            continue
        option_name = _text(option.get("name"))
        option_label = f"{label} / {option_name}".strip(" /")
        setup = _tire_setup_from_row(option)
        if setup is None:
            issues.append(
                CarLibraryValidationIssue(
                    rule="tire_dimensions_invalid",
                    entity=entity,
                    message=f"{option_label} does not expose usable tire dimensions",
                )
            )
            continue
        _validate_tire_setup(setup, entity=entity, label=option_label, issues=issues)
        match = _RIM_SUFFIX_RE.search(option_name)
        if match is not None and setup.front.rim_in != float(match.group("rim")):
            issues.append(
                CarLibraryValidationIssue(
                    rule="tire_option_name_rim_mismatch",
                    entity=entity,
                    message=(
                        f'{option_label} name suffix says {match.group("rim")}" '
                        f"but front rim is {setup.front.rim_in}"
                    ),
                )
            )


def _validate_tire_setup(
    setup: AxleTireSetup | _ResolvedTireSetup,
    *,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    _validate_tire_spec(setup.front, entity=entity, label=f"{label} front tire", issues=issues)
    _validate_tire_spec(setup.rear, entity=entity, label=f"{label} rear tire", issues=issues)


def _validate_tire_spec(
    spec: TireSpec,
    *,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    diameter = spec.diameter_mm
    if not _in_range(diameter, _TIRE_DIAMETER_RANGE_MM):
        issues.append(
            CarLibraryValidationIssue(
                rule="tire_diameter_range",
                entity=entity,
                message=f"{label} has implausible diameter_mm={diameter:.1f}",
            )
        )


def _tire_setup_from_row(row: Mapping[str, object]) -> _ResolvedTireSetup | None:
    front = _tire_spec_from_dimensions_mapping(row.get("front"))
    rear = _tire_spec_from_dimensions_mapping(row.get("rear"))
    flat = _tire_spec_from_values(
        width=row.get("tire_width_mm"),
        aspect=row.get("tire_aspect_pct"),
        rim=row.get("rim_in"),
    )
    if front is None:
        front = flat
    if rear is None:
        rear = flat
    if front is None or rear is None:
        return None

    return _ResolvedTireSetup(front=front, rear=rear)


def _tire_spec_from_dimensions_mapping(payload: object) -> TireSpec | None:
    if not isinstance(payload, Mapping):
        return None
    return _tire_spec_from_values(
        width=payload.get("width_mm"),
        aspect=payload.get("aspect_pct"),
        rim=payload.get("rim_in"),
    )


def _tire_spec_from_values(*, width: object, aspect: object, rim: object) -> TireSpec | None:
    width_value = _float_or_none(width)
    aspect_value = _float_or_none(aspect)
    rim_value = _float_or_none(rim)
    if width_value is None or aspect_value is None or rim_value is None:
        return None
    return TireSpec.from_aspects(
        {
            "tire_width_mm": width_value,
            "tire_aspect_pct": aspect_value,
            "rim_in": rim_value,
        }
    )


def _filter_allowlisted_issues(
    issues: Sequence[CarLibraryValidationIssue],
    allowlist: Mapping[tuple[str, str], str] | None,
) -> tuple[CarLibraryValidationIssue, ...]:
    allowances = load_car_library_validation_allowlist() if allowlist is None else dict(allowlist)
    return tuple(issue for issue in issues if (issue.rule, issue.entity) not in allowances)


def _format_issue_summary(label: str, issues: Sequence[CarLibraryValidationIssue]) -> str:
    lines = [f"Invalid {label}: {len(issues)} issue(s)"]
    lines.extend(f"- [{issue.rule}] {issue.message}" for issue in issues[:10])
    remaining = len(issues) - 10
    if remaining > 0:
        lines.append(f"- ... and {remaining} more")
    return "\n".join(lines)


def _classify_fuel_type(engine_name: str | None) -> str:
    normalized = (engine_name or "").lower()
    if "phev" in normalized:
        return "PHEV"
    if "electric" in normalized or normalized.startswith("ev "):
        return "EV"
    return "ICE"


def _is_single_speed_gearbox(gearbox_name: str) -> bool:
    return "single-speed" in gearbox_name.lower()


def _model_entity(brand: str, model: str) -> str:
    return f"{brand}|{model}"


def _variant_entity(brand: str, model: str, variant_name: str) -> str:
    return f"{brand}|{model}|{variant_name}"


def _text(value: object) -> str:
    return str(value or "").strip()


def _float_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _in_range(value: float, bounds: tuple[float, float]) -> bool:
    lower, upper = bounds
    return lower <= value <= upper
