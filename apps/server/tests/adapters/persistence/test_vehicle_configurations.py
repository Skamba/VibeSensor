from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import cast
from unittest.mock import patch

from vibesensor.adapters.persistence.vehicle_configurations import (
    _VEHICLE_CONFIG_DATA_DIR,
    load_vehicle_configurations,
)


def _load_sample_shards(count: int) -> list[tuple[Path, list[dict[str, object]]]]:
    shards: list[tuple[Path, list[dict[str, object]]]] = []
    for shard_path in sorted(_VEHICLE_CONFIG_DATA_DIR.rglob("*.json")):
        payload = json.loads(shard_path.read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert all(isinstance(row, dict) for row in payload)
        shards.append((shard_path.relative_to(_VEHICLE_CONFIG_DATA_DIR), cast(list[dict[str, object]], payload)))
        if len(shards) == count:
            return shards
    raise AssertionError(f"Expected at least {count} canonical vehicle-configuration shards")


def _write_shard(
    root: Path,
    relative_path: Path,
    rows: list[dict[str, object]],
) -> None:
    shard_path = root / relative_path
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def test_load_vehicle_configurations_reads_multiple_shards(tmp_path: Path) -> None:
    sample_shards = _load_sample_shards(2)
    expected_ids = {str(row["id"]) for _, rows in sample_shards for row in rows}
    for relative_path, rows in sample_shards:
        _write_shard(tmp_path, relative_path, rows)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()

    assert {config.id for config in loaded} == expected_ids


def test_load_vehicle_configurations_fails_closed_for_duplicate_ids_across_shards(
    tmp_path: Path,
) -> None:
    relative_path, rows = _load_sample_shards(1)[0]
    duplicate_row = copy.deepcopy(rows[0])
    _write_shard(tmp_path, relative_path, [duplicate_row])
    _write_shard(tmp_path, Path("duplicate") / relative_path.name, [duplicate_row])

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_fails_closed_for_invalid_shard(tmp_path: Path) -> None:
    relative_path, rows = _load_sample_shards(1)[0]
    _write_shard(tmp_path, relative_path, rows)
    bad_path = tmp_path / "broken" / "bad.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{not valid json", encoding="utf-8")

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_fails_closed_when_required_evidence_refs_are_missing(
    tmp_path: Path,
) -> None:
    relative_path, rows = _load_sample_shards(1)[0]
    bad_payload = copy.deepcopy(rows)
    bad_drivetrain = cast(dict[str, object], bad_payload[0]["drivetrain"])
    bad_payload[0]["drivetrain"] = {
        "value": bad_drivetrain["value"],
        "confidence": "official_exact",
        "notes": "Broken test payload without evidence refs.",
    }
    _write_shard(tmp_path, relative_path, bad_payload)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []
