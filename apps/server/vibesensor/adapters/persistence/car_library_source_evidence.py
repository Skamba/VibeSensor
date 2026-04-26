"""Machine-checkable source packs for canonical vehicle-configuration evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from vibesensor.domain import VehicleConfiguration, VehicleFieldMetadata
from vibesensor.shared._data_files import resolve_static_data_file

__all__ = [
    "CarSourceDocument",
    "CarSourceEvidenceIssue",
    "CarSourceRegistry",
    "ensure_valid_vehicle_configuration_source_evidence",
    "load_car_source_registry",
    "validate_vehicle_configuration_source_evidence",
]

_SOURCE_PACKS_DIR = resolve_static_data_file("car_sources")


@dataclass(frozen=True, slots=True)
class CarSourceDocument:
    """One canonical source record from a machine-checkable source pack."""

    id: str
    url: str
    title: str
    note: str
    confidence: str


@dataclass(frozen=True, slots=True)
class CarSourceRegistry:
    """Resolved reusable source documents for canonical vehicle rows."""

    sources: dict[str, CarSourceDocument]


@dataclass(frozen=True, slots=True)
class CarSourceEvidenceIssue:
    """One machine-readable canonical evidence validation failure."""

    rule: str
    entity: str
    message: str


def load_car_source_registry(source_packs_dir: Path | None = None) -> CarSourceRegistry:
    """Load and validate the machine-checkable source registry."""

    resolved_source_packs_dir = _SOURCE_PACKS_DIR if source_packs_dir is None else source_packs_dir
    sources: dict[str, CarSourceDocument] = {}
    if not resolved_source_packs_dir.is_dir():
        raise ValueError(f"Car source pack directory is missing: {resolved_source_packs_dir}")

    pack_paths = sorted(resolved_source_packs_dir.glob("*.json"))
    if not pack_paths:
        raise ValueError(f"Car source pack directory is empty: {resolved_source_packs_dir}")

    for path in pack_paths:
        payload = _load_json_object(path)
        pack_id = _required_non_empty_string(payload, "pack_id", path=path)
        rows = payload.get("sources")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{path} must contain a non-empty 'sources' list")
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ValueError(f"{path} source #{index} must be an object")
            source_id = _required_non_empty_string(
                row,
                "id",
                path=path,
                index=index,
            )
            if not source_id.startswith(f"{pack_id}:"):
                raise ValueError(
                    f"{path} source #{index} id={source_id!r} must start with {pack_id!r}:"
                )
            if source_id in sources:
                raise ValueError(f"{path} duplicates source id {source_id!r}")
            sources[source_id] = CarSourceDocument(
                id=source_id,
                url=_required_non_empty_string(row, "url", path=path, index=index),
                title=_required_non_empty_string(row, "title", path=path, index=index),
                note=_required_non_empty_string(row, "note", path=path, index=index),
                confidence=_required_non_empty_string(
                    row,
                    "confidence",
                    path=path,
                    index=index,
                ),
            )

    return CarSourceRegistry(sources=sources)


def ensure_valid_vehicle_configuration_source_evidence(
    configs: Sequence[VehicleConfiguration],
    *,
    registry: CarSourceRegistry | None = None,
) -> None:
    """Raise ``ValueError`` when canonical vehicle configurations lack resolvable evidence."""

    issues = validate_vehicle_configuration_source_evidence(configs, registry=registry)
    if issues:
        raise ValueError(_format_issue_summary(issues))


def validate_vehicle_configuration_source_evidence(
    configs: Sequence[VehicleConfiguration],
    *,
    registry: CarSourceRegistry | None = None,
) -> tuple[CarSourceEvidenceIssue, ...]:
    """Return all evidence-resolution validation issues for canonical vehicle rows."""

    resolved_registry = load_car_source_registry() if registry is None else registry
    issues: list[CarSourceEvidenceIssue] = []
    for config in configs:
        entity = f"{config.brand}|{config.model_name}|{config.variant_name}"
        label = f"{config.brand} {config.model_name} / {config.variant_name}"
        for field_name in config.coverage_policy_fields:
            metadata = config.metadata_for(field_name)
            if metadata is None:
                continue
            issues.extend(
                _validate_metadata_refs(
                    metadata,
                    registry=resolved_registry,
                    entity=entity,
                    label=f"{label} field {field_name!r}",
                )
            )
        if config.gear_ratios_metadata is not None:
            issues.extend(
                _validate_metadata_refs(
                    config.gear_ratios_metadata,
                    registry=resolved_registry,
                    entity=entity,
                    label=f"{label} field 'gear_ratios'",
                )
            )
        for option in config.tire_options:
            if option.metadata is None:
                continue
            issues.extend(
                _validate_metadata_refs(
                    option.metadata,
                    registry=resolved_registry,
                    entity=entity,
                    label=f"{label} tire option {option.name!r}",
                )
            )
        for note in config.verification_notes:
            for ref in note.evidence_refs:
                if ref not in resolved_registry.sources:
                    issues.append(
                        CarSourceEvidenceIssue(
                            rule="missing_source_reference",
                            entity=entity,
                            message=f"{label} verification note references unknown source {ref!r}",
                        )
                    )
        for issue in config.unresolved:
            for ref in issue.evidence_refs:
                if ref not in resolved_registry.sources:
                    issues.append(
                        CarSourceEvidenceIssue(
                            rule="missing_source_reference",
                            entity=entity,
                            message=f"{label} unresolved item references unknown source {ref!r}",
                        )
                    )
    return tuple(issues)


def _validate_metadata_refs(
    metadata: VehicleFieldMetadata,
    *,
    registry: CarSourceRegistry,
    entity: str,
    label: str,
) -> list[CarSourceEvidenceIssue]:
    issues: list[CarSourceEvidenceIssue] = []
    if metadata.requires_evidence_refs and not metadata.evidence_refs:
        issues.append(
            CarSourceEvidenceIssue(
                rule="missing_required_evidence_refs",
                entity=entity,
                message=(
                    f"{label} uses confidence {metadata.confidence!r} but has no evidence_refs"
                ),
            )
        )
        return issues
    for ref in metadata.evidence_refs:
        if ref not in registry.sources:
            issues.append(
                CarSourceEvidenceIssue(
                    rule="missing_source_reference",
                    entity=entity,
                    message=f"{label} references unknown source {ref!r}",
                )
            )
    return issues


def _load_json_object(path: Path) -> Mapping[str, object]:
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not load car source metadata from {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a top-level object")
    return payload


def _required_non_empty_string(
    row: Mapping[str, object],
    key: str,
    *,
    path: Path,
    index: int | None = None,
) -> str:
    value = row.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    location = f"{path} #{index}" if index is not None else str(path)
    raise ValueError(f"{location} missing non-empty {key!r}")


def _format_issue_summary(issues: Sequence[CarSourceEvidenceIssue]) -> str:
    lines = [f"Invalid car source evidence: {len(issues)} issue(s)"]
    lines.extend(f"- [{issue.rule}] {issue.message}" for issue in issues[:10])
    remaining = len(issues) - 10
    if remaining > 0:
        lines.append(f"- ... and {remaining} more")
    return "\n".join(lines)
