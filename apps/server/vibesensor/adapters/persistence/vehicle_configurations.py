"""Canonical exact vehicle-configuration loader."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, cast

from pydantic import ConfigDict, TypeAdapter, ValidationError

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
    VehicleOrderAnalysisPolicy,
)
from vibesensor.shared._data_files import resolve_static_data_file

from .car_library_source_evidence import ensure_valid_vehicle_configuration_source_evidence
from .car_library_validation import ensure_valid_vehicle_configurations

LOGGER = logging.getLogger(__name__)

__all__ = [
    "_VEHICLE_CONFIG_DATA_DIR",
    "load_vehicle_configurations",
]

_VEHICLE_CONFIG_DATA_DIR = resolve_static_data_file("vehicle_configurations")
_STRICT_TYPEDDICT_CONFIG = ConfigDict(extra="forbid")

_NOTES_REF_KEY = "notes_ref"
_NOTE_REF_KEY = "note_ref"
_EVIDENCE_REFS_REF_KEY = "evidence_refs_ref"
_DEFAULT_TIRE_REF_KEY = "default_ref"
_TIRE_SETUP_REF_KEY = "setup_ref"
_DEFINITIONS_KEY = "definitions"
_DEFAULTS_KEY = "defaults"
_CONFIGURATIONS_KEY = "configurations"
_DEFINITIONS_NOTES_KEY = "notes"
_DEFINITIONS_EVIDENCE_KEY = "evidence_ref_sets"
_DEFINITIONS_TIRE_SETUPS_KEY = "tire_setups"


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


class VehicleOrderAnalysisPolicyRow(TypedDict):
    usable_for_engine_order: bool
    usable_for_driveshaft_order: bool
    usable_for_wheel_order: bool
    requires_manual_confirmation: bool


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
    order_analysis_policy: VehicleOrderAnalysisPolicyRow
    market: NotRequired[str]
    model_code: NotRequired[str]
    body_code: NotRequired[str]
    production_start_year: NotRequired[int]
    production_end_year: NotRequired[int]
    engine_code: NotRequired[str]
    engine_name: NotRequired[str]
    verification_notes: NotRequired[list[VehicleConfigurationNoteRow]]
    unresolved: NotRequired[list[VehicleConfigurationIssueRow]]


for _typed_dict in (
    VehicleConfigurationIssueRow,
    VehicleConfigurationNoteRow,
    VehicleConfigurationRow,
    VehicleDrivetrainRow,
    VehicleFieldMetadataRow,
    VehicleNumericFieldRow,
    VehicleNumericSequenceFieldRow,
    VehicleOrderAnalysisPolicyRow,
    VehicleRatiosRow,
    VehicleTireDimensionsRow,
    VehicleTireOptionRow,
    VehicleTireSetupRow,
    VehicleTiresRow,
    VehicleTransmissionRow,
):
    cast(Any, _typed_dict).__pydantic_config__ = _STRICT_TYPEDDICT_CONFIG

_VEHICLE_CONFIGURATION_ADAPTER = TypeAdapter(list[VehicleConfigurationRow])


def _metadata_from_row(row: VehicleFieldMetadataRow) -> VehicleFieldMetadata:
    return VehicleFieldMetadata(
        confidence=row["confidence"],
        evidence_refs=tuple(row.get("evidence_refs", [])),
        verified_at=row.get("verified_at"),
        notes=row.get("notes"),
    )


def _tire_spec_from_dimensions_row(row: VehicleTireDimensionsRow) -> TireSpec:
    spec = TireSpec(
        width_mm=float(row["width_mm"]),
        aspect_pct=float(row["aspect_pct"]),
        rim_in=float(row["rim_in"]),
    )
    return spec


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


def _configuration_from_row(row: VehicleConfigurationRow) -> VehicleConfiguration:
    ratios = row["ratios"]
    default_tire_setup = _tire_setup_from_row(row["tires"]["default"])
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
        drivetrain=row["drivetrain"]["value"],
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
        final_drive_front=(
            ratios["final_drive_front"]["value"] if "final_drive_front" in ratios else None
        ),
        final_drive_front_metadata=(
            _metadata_from_row(ratios["final_drive_front"])
            if "final_drive_front" in ratios
            else None
        ),
        final_drive_rear=(
            ratios["final_drive_rear"]["value"] if "final_drive_rear" in ratios else None
        ),
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
        order_analysis_policy=VehicleOrderAnalysisPolicy(**row["order_analysis_policy"]),
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


def _relative_shard_path(shard_path: Path) -> Path:
    try:
        return shard_path.relative_to(_VEHICLE_CONFIG_DATA_DIR)
    except ValueError:
        return shard_path


class _ShardRefError(ValueError):
    """Raised when a shard contains an unknown or malformed provenance ref."""


def _resolve_shard_refs(
    payload: Any,
    notes_defs: dict[str, str],
    evidence_defs: dict[str, list[str]],
    tire_setup_defs: dict[str, dict[str, Any]],
) -> Any:
    if isinstance(payload, dict):
        resolved: dict[str, Any] = {}
        for key, value in payload.items():
            if key == _NOTES_REF_KEY:
                if not isinstance(value, str) or value not in notes_defs:
                    raise _ShardRefError(f"unknown notes_ref {value!r}")
                if "notes" in payload or "notes" in resolved:
                    raise _ShardRefError("notes_ref conflicts with inline notes")
                resolved["notes"] = notes_defs[value]
            elif key == _NOTE_REF_KEY:
                if not isinstance(value, str) or value not in notes_defs:
                    raise _ShardRefError(f"unknown note_ref {value!r}")
                if "note" in payload or "note" in resolved:
                    raise _ShardRefError("note_ref conflicts with inline note")
                resolved["note"] = notes_defs[value]
            elif key == _EVIDENCE_REFS_REF_KEY:
                if not isinstance(value, str) or value not in evidence_defs:
                    raise _ShardRefError(f"unknown evidence_refs_ref {value!r}")
                if "evidence_refs" in payload or "evidence_refs" in resolved:
                    raise _ShardRefError("evidence_refs_ref conflicts with inline evidence_refs")
                resolved["evidence_refs"] = list(evidence_defs[value])
            elif key == _DEFAULT_TIRE_REF_KEY:
                if not isinstance(value, str) or value not in tire_setup_defs:
                    raise _ShardRefError(f"unknown default_ref {value!r}")
                if "default" in payload or "default" in resolved:
                    raise _ShardRefError("default_ref conflicts with inline default")
                resolved["default"] = _resolve_shard_refs(
                    tire_setup_defs[value], notes_defs, evidence_defs, tire_setup_defs
                )
            elif key == _TIRE_SETUP_REF_KEY:
                if not isinstance(value, str) or value not in tire_setup_defs:
                    raise _ShardRefError(f"unknown setup_ref {value!r}")
                expanded_setup = _resolve_shard_refs(
                    tire_setup_defs[value], notes_defs, evidence_defs, tire_setup_defs
                )
                if not isinstance(expanded_setup, dict):
                    raise _ShardRefError(f"setup_ref {value!r} must resolve to an object")
                for setup_key, setup_value in expanded_setup.items():
                    if setup_key in payload or setup_key in resolved:
                        continue
                    resolved[setup_key] = setup_value
            else:
                resolved[key] = _resolve_shard_refs(
                    value, notes_defs, evidence_defs, tire_setup_defs
                )
        return resolved
    if isinstance(payload, list):
        return [
            _resolve_shard_refs(item, notes_defs, evidence_defs, tire_setup_defs)
            for item in payload
        ]
    return payload


def _validate_definitions(
    raw_definitions: Any,
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, dict[str, Any]]]:
    if not isinstance(raw_definitions, dict):
        raise _ShardRefError("definitions must be an object")
    allowed = {_DEFINITIONS_NOTES_KEY, _DEFINITIONS_EVIDENCE_KEY, _DEFINITIONS_TIRE_SETUPS_KEY}
    extra_keys = set(raw_definitions.keys()) - allowed
    if extra_keys:
        raise _ShardRefError(f"unsupported definitions keys: {sorted(extra_keys)}")

    raw_notes = raw_definitions.get(_DEFINITIONS_NOTES_KEY, {})
    if not isinstance(raw_notes, dict):
        raise _ShardRefError("definitions.notes must be an object")
    notes_defs: dict[str, str] = {}
    for key, value in raw_notes.items():
        if not isinstance(key, str) or not key:
            raise _ShardRefError(f"invalid notes key {key!r}")
        if not isinstance(value, str):
            raise _ShardRefError(f"definitions.notes[{key}] must be a string")
        notes_defs[key] = value

    raw_evidence = raw_definitions.get(_DEFINITIONS_EVIDENCE_KEY, {})
    if not isinstance(raw_evidence, dict):
        raise _ShardRefError("definitions.evidence_ref_sets must be an object")
    evidence_defs: dict[str, list[str]] = {}
    for key, value in raw_evidence.items():
        if not isinstance(key, str) or not key:
            raise _ShardRefError(f"invalid evidence_ref_sets key {key!r}")
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise _ShardRefError(f"definitions.evidence_ref_sets[{key}] must be a list of strings")
        evidence_defs[key] = list(value)

    raw_tire_setups = raw_definitions.get(_DEFINITIONS_TIRE_SETUPS_KEY, {})
    if not isinstance(raw_tire_setups, dict):
        raise _ShardRefError("definitions.tire_setups must be an object")
    tire_setup_defs: dict[str, dict[str, Any]] = {}
    for key, value in raw_tire_setups.items():
        if not isinstance(key, str) or not key:
            raise _ShardRefError(f"invalid tire_setups key {key!r}")
        if not isinstance(value, dict):
            raise _ShardRefError(f"definitions.tire_setups[{key}] must be an object")
        tire_setup_defs[key] = value

    return notes_defs, evidence_defs, tire_setup_defs


def _apply_shard_defaults(raw_configs: list[Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    if not defaults:
        merged_rows: list[dict[str, Any]] = []
        for row in raw_configs:
            if not isinstance(row, dict):
                raise _ShardRefError("each configuration row must be an object")
            merged_rows.append(dict(row))
        return merged_rows

    merged: list[dict[str, Any]] = []
    for row in raw_configs:
        if not isinstance(row, dict):
            raise _ShardRefError("each configuration row must be an object")
        combined: dict[str, Any] = dict(defaults)
        combined.update(row)
        merged.append(combined)
    return merged


def _validate_defaults(raw_defaults: Any) -> dict[str, Any]:
    if not isinstance(raw_defaults, dict):
        raise _ShardRefError("defaults must be an object")
    for key in raw_defaults:
        if not isinstance(key, str) or not key:
            raise _ShardRefError(f"invalid defaults key {key!r}")
    return dict(raw_defaults)


def _expand_shard_payload(data: Any) -> list[dict[str, Any]]:
    """Expand a shard payload into a plain list of vehicle configuration row dicts."""

    if not isinstance(data, dict):
        raise _ShardRefError(
            "shard root must be an object with 'configurations'"
            " (and optional 'definitions', 'defaults')"
        )
    extra_keys = set(data.keys()) - {_DEFINITIONS_KEY, _DEFAULTS_KEY, _CONFIGURATIONS_KEY}
    if extra_keys:
        raise _ShardRefError(f"unsupported shard keys: {sorted(extra_keys)}")

    notes_defs, evidence_defs, tire_setup_defs = _validate_definitions(
        data.get(_DEFINITIONS_KEY, {})
    )
    defaults = _validate_defaults(data.get(_DEFAULTS_KEY, {}))

    raw_configs = data.get(_CONFIGURATIONS_KEY)
    if not isinstance(raw_configs, list):
        raise _ShardRefError("shard 'configurations' must be a list")

    merged_rows = _apply_shard_defaults(raw_configs, defaults)
    expanded = _resolve_shard_refs(merged_rows, notes_defs, evidence_defs, tire_setup_defs)
    return cast(list[dict[str, Any]], expanded)


def _load_vehicle_configuration_rows() -> list[VehicleConfigurationRow]:
    if not _VEHICLE_CONFIG_DATA_DIR.is_dir():
        LOGGER.warning(
            "Could not load exact vehicle configurations: missing data dir %s",
            _VEHICLE_CONFIG_DATA_DIR,
        )
        return []

    rows: list[VehicleConfigurationRow] = []
    seen_ids: dict[str, Path] = {}
    for shard_path in sorted(_VEHICLE_CONFIG_DATA_DIR.rglob("*.json")):
        try:
            with shard_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, PermissionError, OSError) as exc:
            LOGGER.warning(
                "Could not read exact vehicle configuration shard %s: %s",
                _relative_shard_path(shard_path),
                exc,
            )
            return []

        try:
            expanded = _expand_shard_payload(data)
        except _ShardRefError as exc:
            LOGGER.warning(
                "Exact vehicle configuration shard %s has invalid provenance refs: %s",
                _relative_shard_path(shard_path),
                exc,
            )
            return []

        try:
            shard_rows = _VEHICLE_CONFIGURATION_ADAPTER.validate_python(expanded)
        except ValidationError as exc:
            LOGGER.warning(
                "Exact vehicle configuration shard %s failed validation: %s",
                _relative_shard_path(shard_path),
                exc,
            )
            return []

        for row in shard_rows:
            row_id = row["id"]
            previous_shard = seen_ids.get(row_id)
            if previous_shard is not None and previous_shard != shard_path:
                LOGGER.warning(
                    "Exact vehicle configuration id %s appears in multiple shards: %s and %s",
                    row_id,
                    _relative_shard_path(previous_shard),
                    _relative_shard_path(shard_path),
                )
                return []
            seen_ids.setdefault(row_id, shard_path)
        rows.extend(shard_rows)

    return rows


def _load_vehicle_configurations_snapshot() -> list[VehicleConfiguration]:
    rows = _load_vehicle_configuration_rows()
    if not rows and not _VEHICLE_CONFIG_DATA_DIR.is_dir():
        return []

    try:
        configs = [_configuration_from_row(row) for row in rows]
        ensure_valid_vehicle_configurations(configs)
        ensure_valid_vehicle_configuration_source_evidence(configs)
        return configs
    except ValueError as exc:
        LOGGER.warning(
            "Could not validate exact vehicle configurations from %s: %s",
            _VEHICLE_CONFIG_DATA_DIR,
            exc,
        )
        return []


def load_vehicle_configurations() -> list[VehicleConfiguration]:
    """Load and return a fresh validated canonical configuration snapshot."""

    return _load_vehicle_configurations_snapshot()
