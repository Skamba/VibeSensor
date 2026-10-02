"""Canonical exact vehicle-configuration loader.

Rows are schema-checked (pydantic) and provenance refs are resolved here. The
cross-field plausibility and source-evidence rules for the bundled data run in
the test suite (``tests/test_support/car_library_validation``), not at startup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from vibesensor.adapters.persistence._vehicle_configuration_rows import (
    VehicleConfigurationRow,
    validate_vehicle_configuration_rows,
    vehicle_configuration_from_row,
)
from vibesensor.adapters.persistence._vehicle_configuration_shards import (
    ShardRefError,
    expand_shard_payload,
)
from vibesensor.domain.vehicle_configuration import VehicleConfiguration
from vibesensor.shared._data_files import resolve_static_data_file

LOGGER = logging.getLogger(__name__)

__all__ = [
    "load_vehicle_configurations",
]

_VEHICLE_CONFIG_DATA_DIR = resolve_static_data_file("vehicle_configurations")


def _relative_shard_path(shard_path: Path, *, data_dir: Path) -> Path:
    try:
        return shard_path.relative_to(data_dir)
    except ValueError:
        return shard_path


def _load_vehicle_configuration_rows(*, data_dir: Path) -> list[VehicleConfigurationRow]:
    if not data_dir.is_dir():
        LOGGER.warning(
            "Could not load exact vehicle configurations: missing data dir %s",
            data_dir,
        )
        return []

    rows: list[VehicleConfigurationRow] = []
    seen_ids: dict[str, Path] = {}
    for shard_path in sorted(data_dir.rglob("*.json")):
        try:
            with shard_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, PermissionError, OSError) as exc:
            LOGGER.warning(
                "Could not read exact vehicle configuration shard %s: %s",
                _relative_shard_path(shard_path, data_dir=data_dir),
                exc,
            )
            return []

        try:
            expanded = expand_shard_payload(data)
        except ShardRefError as exc:
            LOGGER.warning(
                "Exact vehicle configuration shard %s has invalid provenance refs: %s",
                _relative_shard_path(shard_path, data_dir=data_dir),
                exc,
            )
            return []

        try:
            shard_rows = validate_vehicle_configuration_rows(expanded)
        except ValidationError as exc:
            LOGGER.warning(
                "Exact vehicle configuration shard %s failed validation: %s",
                _relative_shard_path(shard_path, data_dir=data_dir),
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
                    _relative_shard_path(previous_shard, data_dir=data_dir),
                    _relative_shard_path(shard_path, data_dir=data_dir),
                )
                return []
            seen_ids.setdefault(row_id, shard_path)
        rows.extend(shard_rows)

    return rows


def _load_vehicle_configurations_snapshot(*, data_dir: Path) -> list[VehicleConfiguration]:
    rows = _load_vehicle_configuration_rows(data_dir=data_dir)
    if not rows and not data_dir.is_dir():
        return []

    try:
        return [vehicle_configuration_from_row(row) for row in rows]
    except ValueError as exc:
        LOGGER.warning(
            "Could not build exact vehicle configurations from %s: %s",
            data_dir,
            exc,
        )
        return []


def load_vehicle_configurations(*, data_dir: Path | None = None) -> list[VehicleConfiguration]:
    """Load and return a fresh schema-checked vehicle-configuration snapshot."""

    resolved_data_dir = _VEHICLE_CONFIG_DATA_DIR if data_dir is None else data_dir
    return _load_vehicle_configurations_snapshot(data_dir=resolved_data_dir)
