from __future__ import annotations

import copy
from pathlib import Path
from typing import cast

from test_support.vehicle_configuration_shards import (
    load_sample_vehicle_configuration_shards,
    write_vehicle_configuration_shard,
)
from vibesensor.adapters.persistence.vehicle_configurations import load_vehicle_configurations


def _base_fixture() -> tuple[Path, dict[str, object], list[dict[str, object]]]:
    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    return relative_path, fixture, rows


def test_load_vehicle_configurations_rejects_bad_drivetrain_value(tmp_path: Path) -> None:
    relative_path, fixture, rows = _base_fixture()
    drivetrain = cast(dict[str, object], rows[0]["drivetrain"])
    drivetrain["value"] = "BOGUS"
    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)

    assert load_vehicle_configurations(data_dir=tmp_path) == []


def test_load_vehicle_configurations_rejects_tires_with_both_default_and_default_ref(
    tmp_path: Path,
) -> None:
    relative_path, fixture, rows = _base_fixture()
    tires = cast(dict[str, object], rows[0]["tires"])
    tires["default_ref"] = "conflicting_default"
    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)

    assert load_vehicle_configurations(data_dir=tmp_path) == []


def test_load_vehicle_configurations_rejects_override_without_reason(tmp_path: Path) -> None:
    relative_path, fixture, rows = _base_fixture()
    rows[0]["order_analysis_policy_override"] = {"usable_for_wheel_order": False}
    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)

    assert load_vehicle_configurations(data_dir=tmp_path) == []
