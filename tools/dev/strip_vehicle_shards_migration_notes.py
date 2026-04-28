"""Strip legacy migration boilerplate from vehicle configuration shards.

Boilerplate categories removed in this pass:

1. "Migrated from legacy grouped car-library data ..." family/variant notes.
2. "<field>: confidence was 'no_confidence' (manual confirmation required);
    remapped to 'unverified' for schema compliance." remap notes.
3. "Legacy variant-source research previously recorded this variant as ..."
   research-history notes.

These notes describe the historical migration into the canonical exact-row
shape, not vehicle-specific evidence. After removal, vehicle-specific notes
remain attached to their fields and rows. Idempotent.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_BOILERPLATE_PREFIXES: tuple[str, ...] = (
    "Migrated from legacy grouped car-library data",
    "Legacy variant-source research previously recorded this variant",
)
_BOILERPLATE_CONTAINS: tuple[str, ...] = (
    "confidence was 'no_confidence' (manual confirmation required); "
    "remapped to 'unverified' for schema compliance.",
)

_NOTE_KEYS = ("notes", "note")
_REF_KEYS = ("notes_ref", "note_ref")

_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "server"
    / "vibesensor"
    / "data"
    / "vehicle_configurations"
)


def _is_boilerplate(text: str) -> bool:
    for prefix in _BOILERPLATE_PREFIXES:
        if text.startswith(prefix):
            return True
    for needle in _BOILERPLATE_CONTAINS:
        if needle in text:
            return True
    return False


def _boilerplate_notes_keys(notes_defs: dict[str, str]) -> set[str]:
    return {key for key, value in notes_defs.items() if _is_boilerplate(value)}


def _scrub_payload(node: Any, dead_ref_keys: set[str]) -> Any:
    if isinstance(node, dict):
        scrubbed: dict[str, Any] = {}
        for key, value in node.items():
            if key in _NOTE_KEYS and isinstance(value, str) and _is_boilerplate(value):
                continue
            if key in _REF_KEYS and isinstance(value, str) and value in dead_ref_keys:
                continue
            scrubbed[key] = _scrub_payload(value, dead_ref_keys)
        return scrubbed
    if isinstance(node, list):
        if all(isinstance(item, dict) for item in node):
            cleaned: list[dict[str, Any]] = []
            for item in node:
                inline_note = item.get("note") if isinstance(item, dict) else None
                if isinstance(inline_note, str) and _is_boilerplate(inline_note):
                    continue
                inline_ref = item.get("note_ref") if isinstance(item, dict) else None
                if isinstance(inline_ref, str) and inline_ref in dead_ref_keys:
                    continue
                cleaned.append(_scrub_payload(item, dead_ref_keys))
            return cleaned
        return [_scrub_payload(item, dead_ref_keys) for item in node]
    return node


def _used_ref_keys(node: Any, ref_keys: Iterable[str]) -> set[str]:
    found: set[str] = set()
    stack: list[Any] = [node]
    targets = set(ref_keys)
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, value in cur.items():
                if key in targets and isinstance(value, str):
                    found.add(value)
                else:
                    stack.append(value)
        elif isinstance(cur, list):
            stack.extend(cur)
    return found


def _process_shard(path: Path, write: bool) -> tuple[int, int, bool]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "configurations" not in raw:
        return (0, 0, False)
    notes_defs = raw.get("definitions", {}).get("notes", {})
    dead_keys = (
        _boilerplate_notes_keys(notes_defs) if isinstance(notes_defs, dict) else set()
    )

    new_payload: dict[str, Any] = dict(raw)
    new_payload["configurations"] = _scrub_payload(raw["configurations"], dead_keys)

    if isinstance(notes_defs, dict):
        used = _used_ref_keys(new_payload["configurations"], _REF_KEYS)
        kept_notes = {
            k: v for k, v in notes_defs.items() if k in used and not _is_boilerplate(v)
        }
        definitions = dict(raw.get("definitions", {}))
        if kept_notes:
            definitions["notes"] = kept_notes
        else:
            definitions.pop("notes", None)
        if definitions:
            new_payload["definitions"] = definitions
        else:
            new_payload.pop("definitions", None)

    before = path.stat().st_size
    new_text = json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n"
    changed = new_text.encode("utf-8") != path.read_bytes()
    if write and changed:
        path.write_text(new_text, encoding="utf-8")
        after = path.stat().st_size
    else:
        after = len(new_text.encode("utf-8")) if changed else before
    return (before, after, changed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="report only; do not write"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_DATA_DIR,
        help="vehicle_configurations directory",
    )
    args = parser.parse_args()

    total_before = 0
    total_after = 0
    changed = 0
    shards = sorted(args.data_dir.rglob("*.json"))
    for shard in shards:
        before, after, did_change = _process_shard(shard, write=not args.check)
        total_before += before
        total_after += after
        if did_change:
            changed += 1
    delta = total_before - total_after
    pct = (delta / total_before * 100.0) if total_before else 0.0
    print(
        f"shards={len(shards)} changed={changed} before={total_before} "
        f"after={total_after} saved={delta} ({pct:.1f}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
