"""Validation flow for derived legacy/grouped car-picker rows."""

from __future__ import annotations

from collections.abc import Mapping

from ._car_library_validation_common import (
    CarLibraryValidationIssue,
    model_entity,
    text,
    variant_entity,
)
from ._car_library_validation_powertrain import (
    validate_drivetrain_badges,
    validate_gearboxes,
    validate_manual_or_automatic_claims,
    validate_powertrain_gearbox_consistency,
)
from ._car_library_validation_tires import validate_default_tire, validate_tire_options


def validate_legacy_entry(
    entry: Mapping[str, object],
    issues: list[CarLibraryValidationIssue],
) -> None:
    brand = text(entry.get("brand"))
    model = text(entry.get("model"))
    entry_entity = model_entity(brand, model)
    entry_label = f"{brand} {model}".strip()

    validate_gearboxes(
        entry.get("gearboxes"),
        entity=entry_entity,
        label=entry_label,
        issues=issues,
    )
    validate_default_tire(
        entity=entry_entity,
        label=f"{entry_label} default tire",
        width=entry.get("tire_width_mm"),
        aspect=entry.get("tire_aspect_pct"),
        rim=entry.get("rim_in"),
        issues=issues,
    )
    validate_tire_options(
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
        variant_name = text(variant.get("name"))
        variant_entity_value = variant_entity(brand, model, variant_name)
        variant_label = f"{entry_label} / {variant_name}".strip(" /")

        if variant_name in seen_variants:
            issues.append(
                CarLibraryValidationIssue(
                    rule="duplicate_variant_name",
                    entity=variant_entity_value,
                    message=f"{variant_label} duplicates a variant name within the same model",
                )
            )
        seen_variants.add(variant_name)

        validate_drivetrain_badges(
            variant_name,
            drivetrain=text(variant.get("drivetrain")),
            entity=variant_entity_value,
            label=variant_label,
            issues=issues,
        )
        variant_gearboxes = variant.get("gearboxes")
        effective_gearboxes = (
            variant_gearboxes if isinstance(variant_gearboxes, list) else entry.get("gearboxes")
        )
        if isinstance(variant_gearboxes, list):
            validate_gearboxes(
                variant_gearboxes,
                entity=variant_entity_value,
                label=variant_label,
                issues=issues,
            )
        validate_powertrain_gearbox_consistency(
            engine_name=text(variant.get("engine")),
            gearboxes=effective_gearboxes,
            entity=variant_entity_value,
            label=variant_label,
            issues=issues,
        )
        validate_manual_or_automatic_claims(
            variant_name=variant_name,
            gearboxes=effective_gearboxes,
            entity=variant_entity_value,
            label=variant_label,
            issues=issues,
        )
        if "tire_width_mm" in variant or "tire_aspect_pct" in variant or "rim_in" in variant:
            validate_default_tire(
                entity=variant_entity_value,
                label=f"{variant_label} default tire",
                width=variant.get("tire_width_mm", entry.get("tire_width_mm")),
                aspect=variant.get("tire_aspect_pct", entry.get("tire_aspect_pct")),
                rim=variant.get("rim_in", entry.get("rim_in")),
                issues=issues,
            )
        if isinstance(variant.get("tire_options"), list):
            validate_tire_options(
                variant.get("tire_options"),
                entity=variant_entity_value,
                label=variant_label,
                issues=issues,
            )
