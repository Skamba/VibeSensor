"""Machine-checkable source packs and provenance evidence for exact car rows."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from vibesensor.domain import VehicleConfiguration, VehicleFieldConfidence
from vibesensor.shared._data_files import resolve_static_data_file

__all__ = [
    "CarEvidenceRecord",
    "CarSourceDocument",
    "CarSourceEvidenceIssue",
    "CarSourceRegistry",
    "ensure_valid_vehicle_configuration_source_evidence",
    "load_car_source_registry",
    "validate_vehicle_configuration_source_evidence",
]

_SOURCE_PACKS_DIR = resolve_static_data_file("car_sources")
_EVIDENCE_FILE = resolve_static_data_file("car_library_evidence.json")
_EVIDENCE_REQUIRED_CONFIDENCES: set[VehicleFieldConfidence] = {
    "official_exact",
    "official_derived",
    "reputable_secondary_crosschecked",
}


@dataclass(frozen=True, slots=True)
class CarSourceDocument:
    """One canonical source record from a machine-checkable source pack."""

    id: str
    url: str
    title: str
    note: str
    confidence: str


@dataclass(frozen=True, slots=True)
class CarEvidenceRecord:
    """One provenance evidence entry keyed by ``VehicleFieldProvenance.source_id``."""

    id: str
    summary: str
    source_refs: tuple[str, ...]
    legacy_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CarSourceRegistry:
    """Resolved source documents and evidence entries for exact vehicle rows."""

    sources: dict[str, CarSourceDocument]
    evidence: dict[str, CarEvidenceRecord]


@dataclass(frozen=True, slots=True)
class CarSourceEvidenceIssue:
    """One machine-readable provenance evidence validation failure."""

    rule: str
    entity: str
    message: str


def load_car_source_registry(
    source_packs_dir: Path | None = None,
    evidence_file: Path | None = None,
) -> CarSourceRegistry:
    """Load and validate the machine-checkable source registry."""

    resolved_source_packs_dir = _SOURCE_PACKS_DIR if source_packs_dir is None else source_packs_dir
    resolved_evidence_file = _EVIDENCE_FILE if evidence_file is None else evidence_file
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

    payload = _load_json_object(resolved_evidence_file)
    rows = payload.get("evidence")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{resolved_evidence_file} must contain a non-empty 'evidence' list")

    evidence: dict[str, CarEvidenceRecord] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"{resolved_evidence_file} evidence #{index} must be an object")
        evidence_id = _required_non_empty_string(
            row,
            "id",
            path=resolved_evidence_file,
            index=index,
        )
        if evidence_id in evidence:
            raise ValueError(f"{resolved_evidence_file} duplicates evidence id {evidence_id!r}")
        source_refs = _required_string_list(
            row,
            "source_refs",
            path=resolved_evidence_file,
            index=index,
        )
        for source_ref in source_refs:
            if source_ref not in sources:
                raise ValueError(
                    f"{resolved_evidence_file} evidence id={evidence_id!r} references unknown "
                    f"source {source_ref!r}"
                )
        evidence[evidence_id] = CarEvidenceRecord(
            id=evidence_id,
            summary=_required_non_empty_string(
                row,
                "summary",
                path=resolved_evidence_file,
                index=index,
            ),
            source_refs=source_refs,
            legacy_refs=_optional_string_list(row, "legacy_refs"),
        )

    return CarSourceRegistry(sources=sources, evidence=evidence)


def ensure_valid_vehicle_configuration_source_evidence(
    configs: Sequence[VehicleConfiguration],
    *,
    registry: CarSourceRegistry | None = None,
) -> None:
    """Raise ``ValueError`` when exact vehicle configurations lack resolvable evidence."""

    issues = validate_vehicle_configuration_source_evidence(configs, registry=registry)
    if issues:
        raise ValueError(_format_issue_summary(issues))


def validate_vehicle_configuration_source_evidence(
    configs: Sequence[VehicleConfiguration],
    *,
    registry: CarSourceRegistry | None = None,
) -> tuple[CarSourceEvidenceIssue, ...]:
    """Return all provenance-evidence validation issues for exact vehicle rows."""

    resolved_registry = load_car_source_registry() if registry is None else registry
    issues: list[CarSourceEvidenceIssue] = []
    for config in configs:
        entity = f"{config.brand}|{config.model_name}|{config.variant_name}"
        label = f"{config.brand} {config.model_name} / {config.variant_name}"
        for entry in config.field_provenance:
            if entry.confidence in _EVIDENCE_REQUIRED_CONFIDENCES and not entry.source_id:
                issues.append(
                    CarSourceEvidenceIssue(
                        rule="missing_required_source_id",
                        entity=entity,
                        message=(
                            f"{label} field {entry.field_name!r} uses confidence "
                            f"{entry.confidence!r} but has no source_id"
                        ),
                    )
                )
                continue
            if entry.source_id and entry.source_id not in resolved_registry.evidence:
                issues.append(
                    CarSourceEvidenceIssue(
                        rule="missing_source_evidence",
                        entity=entity,
                        message=(
                            f"{label} field {entry.field_name!r} references unknown "
                            f"source_id {entry.source_id!r}"
                        ),
                    )
                )
    return tuple(issues)


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


def _required_string_list(
    row: Mapping[str, object],
    key: str,
    *,
    path: Path,
    index: int,
) -> tuple[str, ...]:
    value = row.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} #{index} must contain a non-empty {key!r} list")
    items = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if len(items) != len(value):
        raise ValueError(f"{path} #{index} contains an invalid {key!r} entry")
    return items


def _optional_string_list(row: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = row.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"Optional field {key!r} must be a list when present")
    items = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if len(items) != len(value):
        raise ValueError(f"Optional field {key!r} contains an invalid entry")
    return items


def _format_issue_summary(issues: Sequence[CarSourceEvidenceIssue]) -> str:
    lines = [f"Invalid car source evidence: {len(issues)} issue(s)"]
    lines.extend(f"- [{issue.rule}] {issue.message}" for issue in issues[:10])
    remaining = len(issues) - 10
    if remaining > 0:
        lines.append(f"- ... and {remaining} more")
    return "\n".join(lines)
