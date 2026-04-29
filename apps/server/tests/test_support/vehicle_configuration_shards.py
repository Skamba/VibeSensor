from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from vibesensor.shared._data_files import resolve_static_data_file

_CANONICAL_VEHICLE_CONFIGURATION_DATA_DIR = resolve_static_data_file("vehicle_configurations")


def load_sample_vehicle_configuration_shards(count: int) -> list[tuple[Path, dict[str, object]]]:
    shards: list[tuple[Path, dict[str, object]]] = []
    for shard_path in sorted(_CANONICAL_VEHICLE_CONFIGURATION_DATA_DIR.rglob("*.json")):
        payload = json.loads(shard_path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        configs = payload.get("configurations")
        assert isinstance(configs, list)
        shards.append(
            (
                shard_path.relative_to(_CANONICAL_VEHICLE_CONFIGURATION_DATA_DIR),
                cast(dict[str, object], payload),
            )
        )
        if len(shards) == count:
            return shards
    raise AssertionError(f"Expected at least {count} canonical vehicle-configuration shards")


def write_vehicle_configuration_shard(
    root: Path,
    relative_path: Path,
    shard: dict[str, object],
) -> None:
    shard_path = root / relative_path
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_path.write_text(json.dumps(shard, indent=2) + "\n", encoding="utf-8")
