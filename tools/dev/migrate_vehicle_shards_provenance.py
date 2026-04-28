"""Migrate canonical vehicle configuration shards to use shard-local provenance refs.

Each shard becomes::

    {
      "definitions": {
        "notes": {"n1": "..."},
        "evidence_ref_sets": {"e1": ["source:a", "source:b"]}
      },
      "configurations": [ ... ]
    }

Repeated `notes` strings and `evidence_refs` arrays within a shard are lifted
into the shard-local definitions, replaced inline with `notes_ref` /
`note_ref` / `evidence_refs_ref` keys. Unique values stay inline.

Re-runnable: existing shard-object payloads are normalized rather than nested.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARD_DIR = (
    REPO_ROOT / "apps" / "server" / "vibesensor" / "data" / "vehicle_configurations"
)

_NOTES_KEYS = ("notes", "note")
_EVIDENCE_KEY = "evidence_refs"

_REF_KEYS = {"notes_ref", "note_ref", "evidence_refs_ref"}


def _resolve_existing_refs(
    payload: Any, notes: dict[str, str], evidence: dict[str, list[str]]
) -> Any:
    """Inline any pre-existing refs so we can re-compute fresh definitions."""

    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "notes_ref":
                out["notes"] = notes[value]
            elif key == "note_ref":
                out["note"] = notes[value]
            elif key == "evidence_refs_ref":
                out["evidence_refs"] = list(evidence[value])
            else:
                out[key] = _resolve_existing_refs(value, notes, evidence)
        return out
    if isinstance(payload, list):
        return [_resolve_existing_refs(item, notes, evidence) for item in payload]
    return payload


def _load_inline_rows(shard_path: Path) -> list[dict[str, Any]]:
    data = json.loads(shard_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "configurations" in data:
        defs = data.get("definitions", {}) or {}
        notes = defs.get("notes", {}) or {}
        evidence = defs.get("evidence_ref_sets", {}) or {}
        return _resolve_existing_refs(data["configurations"], notes, evidence)
    raise ValueError(f"Unrecognized shard shape: {shard_path}")


def _walk_field_metadata(
    node: Any, notes_counter: Counter[str], evidence_counter: Counter[str]
) -> None:
    """Count `notes`/`note` strings and `evidence_refs` arrays anywhere in node."""

    if isinstance(node, dict):
        for key, value in node.items():
            if key in _NOTES_KEYS and isinstance(value, str):
                notes_counter[value] += 1
            elif key == _EVIDENCE_KEY and isinstance(value, list):
                evidence_counter[json.dumps(value, separators=(",", ":"))] += 1
            else:
                _walk_field_metadata(value, notes_counter, evidence_counter)
    elif isinstance(node, list):
        for item in node:
            _walk_field_metadata(item, notes_counter, evidence_counter)


def _build_definitions(
    rows: list[dict[str, Any]], min_count: int = 2
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, str], dict[str, str]]:
    """Return (notes_defs, evidence_defs, notes_value_to_key, evidence_json_to_key)."""

    notes_counter: Counter[str] = Counter()
    evidence_counter: Counter[str] = Counter()
    _walk_field_metadata(rows, notes_counter, evidence_counter)

    notes_defs: dict[str, str] = {}
    notes_value_to_key: dict[str, str] = {}
    for value, count in notes_counter.most_common():
        if count < min_count:
            continue
        key = f"n{len(notes_defs) + 1}"
        notes_defs[key] = value
        notes_value_to_key[value] = key

    evidence_defs: dict[str, list[str]] = {}
    evidence_json_to_key: dict[str, str] = {}
    for value_json, count in evidence_counter.most_common():
        if count < min_count:
            continue
        key = f"e{len(evidence_defs) + 1}"
        evidence_defs[key] = json.loads(value_json)
        evidence_json_to_key[value_json] = key

    return notes_defs, evidence_defs, notes_value_to_key, evidence_json_to_key


def _rewrite_with_refs(
    node: Any,
    notes_value_to_key: dict[str, str],
    evidence_json_to_key: dict[str, str],
) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if (
                key == "notes"
                and isinstance(value, str)
                and value in notes_value_to_key
            ):
                out["notes_ref"] = notes_value_to_key[value]
            elif (
                key == "note" and isinstance(value, str) and value in notes_value_to_key
            ):
                out["note_ref"] = notes_value_to_key[value]
            elif key == _EVIDENCE_KEY and isinstance(value, list):
                blob = json.dumps(value, separators=(",", ":"))
                if blob in evidence_json_to_key:
                    out["evidence_refs_ref"] = evidence_json_to_key[blob]
                else:
                    out[key] = list(value)
            else:
                out[key] = _rewrite_with_refs(
                    value, notes_value_to_key, evidence_json_to_key
                )
        return out
    if isinstance(node, list):
        return [
            _rewrite_with_refs(item, notes_value_to_key, evidence_json_to_key)
            for item in node
        ]
    return node


def _migrate_shard(shard_path: Path) -> tuple[int, int]:
    rows = _load_inline_rows(shard_path)
    notes_defs, evidence_defs, n_lookup, e_lookup = _build_definitions(rows)
    rewritten = _rewrite_with_refs(rows, n_lookup, e_lookup)

    output: dict[str, Any] = {}
    if notes_defs or evidence_defs:
        defs: dict[str, Any] = {}
        if notes_defs:
            defs["notes"] = notes_defs
        if evidence_defs:
            defs["evidence_ref_sets"] = evidence_defs
        output["definitions"] = defs
    output["configurations"] = rewritten

    before = shard_path.stat().st_size
    shard_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    after = shard_path.stat().st_size
    return before, after


def main(argv: list[str] | None = None) -> int:
    target_dir = SHARD_DIR
    if argv:
        target_dir = Path(argv[0])
    shards = sorted(target_dir.rglob("*.json"))
    total_before = 0
    total_after = 0
    for shard in shards:
        before, after = _migrate_shard(shard)
        total_before += before
        total_after += after
        print(f"{shard.relative_to(target_dir)}: {before} -> {after} bytes")
    if total_before:
        pct = 100.0 * (total_before - total_after) / total_before
        print(f"TOTAL: {total_before} -> {total_after} bytes ({pct:.1f}% reduction)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
