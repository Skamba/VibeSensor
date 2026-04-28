"""Lift duplicate tire setups into shard-local ``definitions.tire_setups``.

For each shard, scans every row's ``tires.default`` and each option's setup
geometry. Setups appearing two or more times within a shard are lifted into
``definitions.tire_setups`` and replaced with refs:

- ``tires.default`` -> ``tires.default_ref``
- option entry inline geometry -> option entry ``setup_ref``
  (option still keeps its ``name`` and any per-option ``evidence_refs`` /
  ``notes`` overrides that differ from the lifted setup)

Idempotent: rehydrates existing refs first, then recomputes the lift.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_DATA_DIR = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "server"
    / "vibesensor"
    / "data"
    / "vehicle_configurations"
)

# Keys that identify a tire setup geometry/metadata for lift purposes.
_SETUP_KEYS = (
    "confidence",
    "front",
    "rear",
    "default_axle_for_speed",
    "evidence_refs",
    "evidence_refs_ref",
    "verified_at",
    "notes",
    "notes_ref",
)


def _hydrate_default(default_block: Any, tire_setups: dict[str, Any]) -> Any:
    if isinstance(default_block, dict) and "default_ref" in default_block:
        ref = default_block["default_ref"]
        if ref in tire_setups:
            return json.loads(json.dumps(tire_setups[ref]))
    return default_block


def _hydrate_option(
    option: dict[str, Any], tire_setups: dict[str, Any]
) -> dict[str, Any]:
    if "setup_ref" not in option:
        return option
    ref = option.pop("setup_ref")
    if ref in tire_setups:
        for k, v in tire_setups[ref].items():
            option.setdefault(k, json.loads(json.dumps(v)))
    return option


def _hydrate_rows(rows: list[Any], tire_setups: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        new_row = json.loads(json.dumps(row))
        tires = new_row.get("tires")
        if isinstance(tires, dict):
            if "default_ref" in tires:
                ref = tires.pop("default_ref")
                if ref in tire_setups:
                    tires["default"] = json.loads(json.dumps(tire_setups[ref]))
            options = tires.get("options")
            if isinstance(options, list):
                tires["options"] = [
                    _hydrate_option(opt, tire_setups) if isinstance(opt, dict) else opt
                    for opt in options
                ]
        out.append(new_row)
    return out


def _setup_signature(setup: dict[str, Any]) -> str:
    return json.dumps(
        {k: setup[k] for k in _SETUP_KEYS if k in setup},
        sort_keys=True,
        ensure_ascii=False,
    )


def _collect_setups(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        tires = row.get("tires") if isinstance(row, dict) else None
        if not isinstance(tires, dict):
            continue
        default = tires.get("default")
        if isinstance(default, dict):
            counts[_setup_signature(default)] += 1
        for opt in tires.get("options", []) or []:
            if isinstance(opt, dict):
                counts[_setup_signature(opt)] += 1
    return counts


def _alloc_key(used: set[str], hint: str) -> str:
    base = hint or "setup"
    if base not in used:
        used.add(base)
        return base
    i = 2
    while True:
        candidate = f"{base}_{i}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        i += 1


def _hint_for_setup(setup: dict[str, Any]) -> str:
    front = setup.get("front") or {}
    rim = front.get("rim_in")
    width = front.get("width_mm")
    if rim and width:
        return f"setup_{int(width)}_{int(rim)}"
    return "setup"


def _replace_setup_with_ref(
    node: dict[str, Any], ref: str, *, is_default: bool
) -> dict[str, Any]:
    if is_default:
        return {"default_ref": ref}
    out: dict[str, Any] = {"setup_ref": ref}
    if "name" in node:
        out["name"] = node["name"]
    return out


def _process_shard(path: Path, write: bool) -> tuple[int, int, bool]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "configurations" not in raw:
        return (0, 0, False)
    rows = raw.get("configurations") or []
    if not isinstance(rows, list):
        return (0, 0, False)

    existing_defs = raw.get("definitions") or {}
    existing_tire_setups = existing_defs.get("tire_setups") or {}
    hydrated = _hydrate_rows(rows, existing_tire_setups)

    counts = _collect_setups(hydrated)
    candidates = {sig: count for sig, count in counts.items() if count >= 2}

    if not candidates:
        new_defs = {k: v for k, v in existing_defs.items() if k != "tire_setups"}
        new_payload = dict(raw)
        if new_defs:
            new_payload["definitions"] = new_defs
        else:
            new_payload.pop("definitions", None)
        new_payload["configurations"] = hydrated
    else:
        used_keys: set[str] = set()
        sig_to_key: dict[str, str] = {}
        sig_to_setup: dict[str, dict[str, Any]] = {}
        for sig in candidates:
            setup = json.loads(sig)
            key = _alloc_key(used_keys, _hint_for_setup(setup))
            sig_to_key[sig] = key
            sig_to_setup[sig] = setup

        new_rows: list[dict[str, Any]] = []
        for row in hydrated:
            new_row = json.loads(json.dumps(row))
            tires = new_row.get("tires")
            if isinstance(tires, dict):
                default = tires.get("default")
                if isinstance(default, dict):
                    sig = _setup_signature(default)
                    if sig in sig_to_key:
                        tires.pop("default", None)
                        tires["default_ref"] = sig_to_key[sig]
                options = tires.get("options")
                if isinstance(options, list):
                    new_options: list[dict[str, Any]] = []
                    for opt in options:
                        if not isinstance(opt, dict):
                            new_options.append(opt)
                            continue
                        sig = _setup_signature(opt)
                        if sig in sig_to_key:
                            new_options.append(
                                _replace_setup_with_ref(
                                    opt, sig_to_key[sig], is_default=False
                                )
                            )
                        else:
                            new_options.append(opt)
                    tires["options"] = new_options
            new_rows.append(new_row)

        tire_setups_section = {
            sig_to_key[sig]: sig_to_setup[sig] for sig in sorted(sig_to_key)
        }
        new_defs = dict(existing_defs)
        new_defs["tire_setups"] = tire_setups_section
        new_payload = dict(raw)
        new_payload["definitions"] = new_defs
        new_payload["configurations"] = new_rows

    # canonical ordering: definitions, defaults, configurations
    ordered: dict[str, Any] = {}
    for key in ("definitions", "defaults", "configurations"):
        if key in new_payload:
            ordered[key] = new_payload[key]
    for key in new_payload:
        if key not in ordered:
            ordered[key] = new_payload[key]

    before = path.stat().st_size
    new_text = json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"
    changed = new_text.encode("utf-8") != path.read_bytes()
    if write and changed:
        path.write_text(new_text, encoding="utf-8")
        after = path.stat().st_size
    else:
        after = len(new_text.encode("utf-8")) if changed else before
    return (before, after, changed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=_DATA_DIR)
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
