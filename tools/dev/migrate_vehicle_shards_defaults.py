"""Lift uniform row-level fields into shard-level ``defaults``.

Idempotent: rehydrates existing ``defaults`` into rows, recomputes the lift, then
rewrites the shard. Only scalar fields that appear identically in every row are
lifted, so behavior is preserved.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LIFT_CANDIDATES = (
    "brand",
    "type",
    "market",
    "model_code",
    "body_code",
    "model_name",
    "production_start_year",
    "production_end_year",
)

_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "server"
    / "vibesensor"
    / "data"
    / "vehicle_configurations"
)


def _hydrate(
    rows: list[dict[str, Any]], defaults: dict[str, Any]
) -> list[dict[str, Any]]:
    if not defaults:
        return [dict(row) for row in rows]
    hydrated: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(defaults)
        merged.update(row)
        hydrated.append(merged)
    return hydrated


def _compute_defaults(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    out: dict[str, Any] = {}
    for key in LIFT_CANDIDATES:
        if not all(key in row for row in rows):
            continue
        first = rows[0][key]
        if all(row[key] == first for row in rows):
            out[key] = first
    return out


def _strip_defaults_from_rows(
    rows: list[dict[str, Any]], defaults: dict[str, Any]
) -> list[dict[str, Any]]:
    if not defaults:
        return rows
    stripped: list[dict[str, Any]] = []
    for row in rows:
        new_row = {
            k: v
            for k, v in row.items()
            if not (k in defaults and row[k] == defaults[k])
        }
        stripped.append(new_row)
    return stripped


def _process_shard(path: Path, write: bool) -> tuple[int, int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "configurations" not in raw:
        return (0, 0)
    rows = raw.get("configurations") or []
    if not isinstance(rows, list):
        return (0, 0)

    existing_defaults = raw.get("defaults") or {}
    hydrated = _hydrate(rows, existing_defaults)
    new_defaults = _compute_defaults(hydrated)
    new_rows = _strip_defaults_from_rows(hydrated, new_defaults)

    new_payload: dict[str, Any] = {}
    if "definitions" in raw:
        new_payload["definitions"] = raw["definitions"]
    if new_defaults:
        new_payload["defaults"] = new_defaults
    new_payload["configurations"] = new_rows

    before = path.stat().st_size
    new_text = json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n"
    if write:
        path.write_text(new_text, encoding="utf-8")
        after = path.stat().st_size
    else:
        after = len(new_text.encode("utf-8"))
    return (before, after)


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
    for shard in sorted(args.data_dir.rglob("*.json")):
        before, after = _process_shard(shard, write=not args.check)
        total_before += before
        total_after += after
        if before != after:
            changed += 1
    delta = total_before - total_after
    pct = (delta / total_before * 100.0) if total_before else 0.0
    print(
        f"shards={len(list(args.data_dir.rglob('*.json')))} changed={changed} "
        f"before={total_before} after={total_after} saved={delta} ({pct:.1f}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
