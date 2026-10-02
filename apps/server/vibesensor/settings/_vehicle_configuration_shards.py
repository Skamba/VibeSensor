"""Shard-local ref/default expansion for canonical vehicle configurations."""

from __future__ import annotations

from typing import Any, cast

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


class ShardRefError(ValueError):
    """Raised when a shard contains an unknown or malformed provenance ref."""


def expand_shard_payload(data: Any) -> list[dict[str, Any]]:
    """Expand a shard payload into plain vehicle configuration row dicts."""

    if not isinstance(data, dict):
        raise ShardRefError(
            "shard root must be an object with 'configurations'"
            " (and optional 'definitions', 'defaults')"
        )
    extra_keys = set(data.keys()) - {_DEFINITIONS_KEY, _DEFAULTS_KEY, _CONFIGURATIONS_KEY}
    if extra_keys:
        raise ShardRefError(f"unsupported shard keys: {sorted(extra_keys)}")

    notes_defs, evidence_defs, tire_setup_defs = _validate_definitions(
        data.get(_DEFINITIONS_KEY, {})
    )
    defaults = _validate_defaults(data.get(_DEFAULTS_KEY, {}))

    raw_configs = data.get(_CONFIGURATIONS_KEY)
    if not isinstance(raw_configs, list):
        raise ShardRefError("shard 'configurations' must be a list")

    merged_rows = _apply_shard_defaults(raw_configs, defaults)
    expanded = _resolve_shard_refs(merged_rows, notes_defs, evidence_defs, tire_setup_defs)
    return cast(list[dict[str, Any]], expanded)


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
                    raise ShardRefError(f"unknown notes_ref {value!r}")
                if "notes" in payload or "notes" in resolved:
                    raise ShardRefError("notes_ref conflicts with inline notes")
                resolved["notes"] = notes_defs[value]
            elif key == _NOTE_REF_KEY:
                if not isinstance(value, str) or value not in notes_defs:
                    raise ShardRefError(f"unknown note_ref {value!r}")
                if "note" in payload or "note" in resolved:
                    raise ShardRefError("note_ref conflicts with inline note")
                resolved["note"] = notes_defs[value]
            elif key == _EVIDENCE_REFS_REF_KEY:
                if not isinstance(value, str) or value not in evidence_defs:
                    raise ShardRefError(f"unknown evidence_refs_ref {value!r}")
                if "evidence_refs" in payload or "evidence_refs" in resolved:
                    raise ShardRefError("evidence_refs_ref conflicts with inline evidence_refs")
                resolved["evidence_refs"] = list(evidence_defs[value])
            elif key == _DEFAULT_TIRE_REF_KEY:
                if not isinstance(value, str) or value not in tire_setup_defs:
                    raise ShardRefError(f"unknown default_ref {value!r}")
                if "default" in payload or "default" in resolved:
                    raise ShardRefError("default_ref conflicts with inline default")
                resolved["default"] = _resolve_shard_refs(
                    tire_setup_defs[value], notes_defs, evidence_defs, tire_setup_defs
                )
            elif key == _TIRE_SETUP_REF_KEY:
                if not isinstance(value, str) or value not in tire_setup_defs:
                    raise ShardRefError(f"unknown setup_ref {value!r}")
                expanded_setup = _resolve_shard_refs(
                    tire_setup_defs[value], notes_defs, evidence_defs, tire_setup_defs
                )
                if not isinstance(expanded_setup, dict):
                    raise ShardRefError(f"setup_ref {value!r} must resolve to an object")
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
        raise ShardRefError("definitions must be an object")
    allowed = {_DEFINITIONS_NOTES_KEY, _DEFINITIONS_EVIDENCE_KEY, _DEFINITIONS_TIRE_SETUPS_KEY}
    extra_keys = set(raw_definitions.keys()) - allowed
    if extra_keys:
        raise ShardRefError(f"unsupported definitions keys: {sorted(extra_keys)}")

    raw_notes = raw_definitions.get(_DEFINITIONS_NOTES_KEY, {})
    if not isinstance(raw_notes, dict):
        raise ShardRefError("definitions.notes must be an object")
    notes_defs: dict[str, str] = {}
    for key, value in raw_notes.items():
        if not isinstance(key, str) or not key:
            raise ShardRefError(f"invalid notes key {key!r}")
        if not isinstance(value, str):
            raise ShardRefError(f"definitions.notes[{key}] must be a string")
        notes_defs[key] = value

    raw_evidence = raw_definitions.get(_DEFINITIONS_EVIDENCE_KEY, {})
    if not isinstance(raw_evidence, dict):
        raise ShardRefError("definitions.evidence_ref_sets must be an object")
    evidence_defs: dict[str, list[str]] = {}
    for key, value in raw_evidence.items():
        if not isinstance(key, str) or not key:
            raise ShardRefError(f"invalid evidence_ref_sets key {key!r}")
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ShardRefError(f"definitions.evidence_ref_sets[{key}] must be a list of strings")
        evidence_defs[key] = list(value)

    raw_tire_setups = raw_definitions.get(_DEFINITIONS_TIRE_SETUPS_KEY, {})
    if not isinstance(raw_tire_setups, dict):
        raise ShardRefError("definitions.tire_setups must be an object")
    tire_setup_defs: dict[str, dict[str, Any]] = {}
    for key, value in raw_tire_setups.items():
        if not isinstance(key, str) or not key:
            raise ShardRefError(f"invalid tire_setups key {key!r}")
        if not isinstance(value, dict):
            raise ShardRefError(f"definitions.tire_setups[{key}] must be an object")
        tire_setup_defs[key] = value

    return notes_defs, evidence_defs, tire_setup_defs


def _apply_shard_defaults(raw_configs: list[Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    if not defaults:
        merged_rows: list[dict[str, Any]] = []
        for row in raw_configs:
            if not isinstance(row, dict):
                raise ShardRefError("each configuration row must be an object")
            merged_rows.append(dict(row))
        return merged_rows

    merged: list[dict[str, Any]] = []
    for row in raw_configs:
        if not isinstance(row, dict):
            raise ShardRefError("each configuration row must be an object")
        combined: dict[str, Any] = dict(defaults)
        combined.update(row)
        merged.append(combined)
    return merged


def _validate_defaults(raw_defaults: Any) -> dict[str, Any]:
    if not isinstance(raw_defaults, dict):
        raise ShardRefError("defaults must be an object")
    for key in raw_defaults:
        if not isinstance(key, str) or not key:
            raise ShardRefError(f"invalid defaults key {key!r}")
    return dict(raw_defaults)
