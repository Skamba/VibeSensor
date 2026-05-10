"""Tire dimension and tire option validation rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.domain import AxleTireSetup, TireSpec

from ._car_library_validation_common import (
    RIM_SUFFIX_RE,
    TIRE_DIAMETER_RANGE_MM,
    CarLibraryValidationIssue,
    float_or_none,
    in_range,
    text,
)


@dataclass(frozen=True, slots=True)
class ResolvedTireSetup:
    front: TireSpec
    rear: TireSpec


def validate_default_tire(
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
    validate_tire_spec(spec, entity=entity, label=label, issues=issues)


def validate_tire_options(
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
        option_name = text(option.get("name"))
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
        validate_tire_setup(setup, entity=entity, label=option_label, issues=issues)
        match = RIM_SUFFIX_RE.search(option_name)
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


def validate_tire_setup(
    setup: AxleTireSetup | ResolvedTireSetup,
    *,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    validate_tire_spec(setup.front, entity=entity, label=f"{label} front tire", issues=issues)
    validate_tire_spec(setup.rear, entity=entity, label=f"{label} rear tire", issues=issues)


def validate_tire_spec(
    spec: TireSpec,
    *,
    entity: str,
    label: str,
    issues: list[CarLibraryValidationIssue],
) -> None:
    diameter = spec.diameter_mm
    if not in_range(diameter, TIRE_DIAMETER_RANGE_MM):
        issues.append(
            CarLibraryValidationIssue(
                rule="tire_diameter_range",
                entity=entity,
                message=f"{label} has implausible diameter_mm={diameter:.1f}",
            )
        )


def _tire_setup_from_row(row: Mapping[str, object]) -> ResolvedTireSetup | None:
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

    return ResolvedTireSetup(front=front, rear=rear)


def _tire_spec_from_dimensions_mapping(payload: object) -> TireSpec | None:
    if not isinstance(payload, Mapping):
        return None
    return _tire_spec_from_values(
        width=payload.get("width_mm"),
        aspect=payload.get("aspect_pct"),
        rim=payload.get("rim_in"),
    )


def _tire_spec_from_values(*, width: object, aspect: object, rim: object) -> TireSpec | None:
    width_value = float_or_none(width)
    aspect_value = float_or_none(aspect)
    rim_value = float_or_none(rim)
    if width_value is None or aspect_value is None or rim_value is None:
        return None
    return TireSpec.from_aspects(
        {
            "tire_width_mm": width_value,
            "tire_aspect_pct": aspect_value,
            "rim_in": rim_value,
        }
    )
