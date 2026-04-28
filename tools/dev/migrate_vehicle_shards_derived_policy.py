"""Migrate vehicle-configuration shards from stored ``order_analysis_policy``
to derived policy + sparse ``order_analysis_policy_override``.

For each row, the order-analysis policy is now computed from row math inputs
(:func:`vibesensor.domain.derive_order_analysis_policy`). Rows whose stored
flags match the derivation drop the block entirely; rows that differ keep
only the differing fields under ``order_analysis_policy_override`` together
with a ``reason`` string.

The migration is idempotent: it accepts shards that already use overrides
and recomputes them from the row math without mutating equivalent state.
"""

from __future__ import annotations

import json
from pathlib import Path

from vibesensor.domain import (
    VehicleOrderAnalysisPolicy,
    derive_order_analysis_policy,
)
from vibesensor.shared._data_files import resolve_static_data_file

DATA_DIR = resolve_static_data_file("vehicle_configurations")
DEFAULT_REASON = "preserved-from-pre-derivation-curated-data"
POLICY_FIELDS = (
    "usable_for_engine_order",
    "usable_for_driveshaft_order",
    "usable_for_wheel_order",
    "requires_manual_confirmation",
)


def _row_drivetrain(row: dict, defaults: dict) -> str | None:
    drivetrain = row.get("drivetrain") or defaults.get("drivetrain")
    if isinstance(drivetrain, dict):
        return drivetrain.get("value")
    return drivetrain


def _row_ratio_value(row: dict, key: str) -> float | None:
    ratios = row.get("ratios") or {}
    block = ratios.get(key)
    if isinstance(block, dict):
        return block.get("value")
    return None


def _stored_policy(row: dict) -> VehicleOrderAnalysisPolicy:
    stored = row.get("order_analysis_policy")
    override = row.get("order_analysis_policy_override")
    derived = derive_order_analysis_policy(
        top_gear_ratio=_row_ratio_value(row, "top_gear_ratio"),
        final_drive_front=_row_ratio_value(row, "final_drive_front"),
        final_drive_rear=_row_ratio_value(row, "final_drive_rear"),
        drivetrain=_row_drivetrain(row, {}),
    )
    if isinstance(stored, dict):
        return VehicleOrderAnalysisPolicy(**{f: stored[f] for f in POLICY_FIELDS})
    if isinstance(override, dict):
        return VehicleOrderAnalysisPolicy(
            **{
                f: override[f] if f in override else getattr(derived, f)
                for f in POLICY_FIELDS
            }
        )
    return derived


def _build_override_block(
    stored: VehicleOrderAnalysisPolicy,
    derived: VehicleOrderAnalysisPolicy,
    existing_reason: str,
) -> dict | None:
    delta = {
        f: getattr(stored, f)
        for f in POLICY_FIELDS
        if getattr(stored, f) != getattr(derived, f)
    }
    if not delta:
        return None
    return {"reason": existing_reason, **delta}


def _migrate_row(row: dict) -> dict:
    existing_override = row.get("order_analysis_policy_override")
    existing_reason = (
        existing_override.get("reason", DEFAULT_REASON)
        if isinstance(existing_override, dict)
        else DEFAULT_REASON
    )
    stored = _stored_policy(row)
    derived = derive_order_analysis_policy(
        top_gear_ratio=_row_ratio_value(row, "top_gear_ratio"),
        final_drive_front=_row_ratio_value(row, "final_drive_front"),
        final_drive_rear=_row_ratio_value(row, "final_drive_rear"),
        drivetrain=_row_drivetrain(row, {}),
    )
    override_block = _build_override_block(stored, derived, existing_reason)
    new_row = {
        k: v
        for k, v in row.items()
        if k not in {"order_analysis_policy", "order_analysis_policy_override"}
    }
    if override_block is not None:
        new_row["order_analysis_policy_override"] = override_block
    return new_row


def _migrate_shard(shard_path: Path) -> bool:
    raw = json.loads(shard_path.read_text())
    rows = raw.get("configurations", [])
    new_rows = [_migrate_row(row) for row in rows]
    if new_rows == rows:
        return False
    raw["configurations"] = new_rows
    shard_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return True


def main() -> int:
    changed = 0
    total = 0
    for shard in sorted(DATA_DIR.rglob("*.json")):
        total += 1
        if _migrate_shard(shard):
            changed += 1
    print(f"Migrated {changed}/{total} shards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
