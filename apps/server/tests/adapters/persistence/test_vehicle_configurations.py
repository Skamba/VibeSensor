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


def _load_sample_shards(count: int) -> list[tuple[Path, dict[str, object]]]:
    shards: list[tuple[Path, dict[str, object]]] = []
    for shard_path in sorted(_VEHICLE_CONFIG_DATA_DIR.rglob("*.json")):
        payload = json.loads(shard_path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert "configurations" in payload
        assert isinstance(payload["configurations"], list)
        shards.append(
            (
                shard_path.relative_to(_VEHICLE_CONFIG_DATA_DIR),
                cast(dict[str, object], payload),
            )
        )
        if len(shards) == count:
            return shards
    raise AssertionError(f"Expected at least {count} canonical vehicle-configuration shards")


def _write_shard(
    root: Path,
    relative_path: Path,
    shard: dict[str, object],
) -> None:
    shard_path = root / relative_path
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    shard_path.write_text(json.dumps(shard, indent=2) + "\n", encoding="utf-8")


def test_load_vehicle_configurations_reads_multiple_shards(tmp_path: Path) -> None:
    sample_shards = _load_sample_shards(2)
    expected_ids = {
        str(row["id"])
        for _, shard in sample_shards
        for row in cast(list[dict[str, object]], shard["configurations"])
    }
    for relative_path, shard in sample_shards:
        _write_shard(tmp_path, relative_path, shard)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()

    assert {config.id for config in loaded} == expected_ids


def test_load_vehicle_configurations_fails_closed_for_duplicate_ids_across_shards(
    tmp_path: Path,
) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    duplicate = copy.deepcopy(shard)
    _write_shard(tmp_path, relative_path, duplicate)
    _write_shard(tmp_path, Path("duplicate") / relative_path.name, duplicate)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_fails_closed_for_invalid_shard(tmp_path: Path) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    _write_shard(tmp_path, relative_path, shard)
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
    relative_path, shard = _load_sample_shards(1)[0]
    bad_payload = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], bad_payload["configurations"])
    bad_drivetrain = cast(dict[str, object], rows[0]["drivetrain"])
    rows[0]["drivetrain"] = {
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


def test_load_vehicle_configurations_expands_notes_and_evidence_refs(tmp_path: Path) -> None:
    """Loader must inline shard-local notes_ref and evidence_refs_ref values."""

    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    drivetrain = cast(dict[str, object], rows[0]["drivetrain"])

    notes_text = "test-only inline ref expansion notes"
    evidence_list = [
        "secondary_technical_sources:carfolio-audi-a3-saloon-8v",
    ]
    fixture.setdefault("definitions", {})
    defs = cast(dict[str, object], fixture["definitions"])
    defs["notes"] = {**cast(dict[str, str], defs.get("notes", {})), "test_note_ref": notes_text}
    defs["evidence_ref_sets"] = {
        **cast(dict[str, list[str]], defs.get("evidence_ref_sets", {})),
        "test_evidence_ref": evidence_list,
    }
    drivetrain.pop("notes", None)
    drivetrain.pop("evidence_refs", None)
    drivetrain["notes_ref"] = "test_note_ref"
    drivetrain["evidence_refs_ref"] = "test_evidence_ref"

    _write_shard(tmp_path, relative_path, fixture)
    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()

    target = next(config for config in loaded if config.id == rows[0]["id"])
    assert target.drivetrain_metadata.notes == notes_text
    assert target.drivetrain_metadata.evidence_refs == tuple(evidence_list)


def test_load_vehicle_configurations_fails_closed_for_unknown_notes_ref(tmp_path: Path) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    drivetrain = cast(dict[str, object], rows[0]["drivetrain"])
    drivetrain.pop("notes", None)
    drivetrain["notes_ref"] = "does_not_exist"
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_fails_closed_for_unknown_evidence_refs_ref(
    tmp_path: Path,
) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    drivetrain = cast(dict[str, object], rows[0]["drivetrain"])
    drivetrain.pop("evidence_refs", None)
    drivetrain["evidence_refs_ref"] = "does_not_exist"
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_rejects_legacy_array_shard(tmp_path: Path) -> None:
    """Bare array shards are no longer accepted; canonical shape is the shard object."""

    relative_path, shard = _load_sample_shards(1)[0]
    legacy_path = tmp_path / relative_path
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps(shard["configurations"], indent=2) + "\n", encoding="utf-8")

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []
