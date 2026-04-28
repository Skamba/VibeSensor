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


def test_load_vehicle_configurations_applies_shard_defaults(tmp_path: Path) -> None:
    """Top-level ``defaults`` merge into rows that lack the field."""

    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    defaults = cast(dict[str, object], fixture.setdefault("defaults", {}))
    expected_brand = defaults["brand"] if "brand" in defaults else rows[0]["brand"]
    for row in rows:
        row.pop("brand", None)
    defaults["brand"] = expected_brand
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()

    assert loaded
    assert all(config.brand == expected_brand for config in loaded)


def test_load_vehicle_configurations_row_overrides_default(tmp_path: Path) -> None:
    """Row-level keys override shard defaults for that row only."""

    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    assert len(rows) >= 1
    defaults = cast(dict[str, object], fixture.setdefault("defaults", {}))
    defaults["brand"] = "DEFAULT_BRAND"
    overridden_id = str(rows[0]["id"])
    rows[0]["brand"] = "ROW_BRAND"
    for row in rows[1:]:
        row.pop("brand", None)
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()

    by_id = {config.id: config for config in loaded}
    assert by_id[overridden_id].brand == "ROW_BRAND"
    for config_id, config in by_id.items():
        if config_id != overridden_id:
            assert config.brand == "DEFAULT_BRAND"


def test_load_vehicle_configurations_fails_closed_when_defaults_miss_required(
    tmp_path: Path,
) -> None:
    """Missing required fields after defaults expansion fail closed."""

    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    defaults = cast(dict[str, object], fixture.setdefault("defaults", {}))
    defaults.pop("brand", None)
    for row in rows:
        row.pop("brand", None)
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    """Unknown shard top-level keys (e.g. typos) are rejected."""

    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    fixture["unexpected"] = {"brand": "X"}
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_expands_default_tire_setup_ref(tmp_path: Path) -> None:
    """Loader must expand ``tires.default_ref`` from ``definitions.tire_setups``."""

    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    target_row = rows[0]
    tires = cast(dict[str, object], target_row["tires"])
    inline_default = cast(dict[str, object], tires.pop("default", None))
    assert inline_default is not None or "default_ref" in tires
    if inline_default is None:
        # Already a ref via prior migration; rebuild an inline default from the ref.
        defs = cast(dict[str, object], fixture.get("definitions", {}))
        ts = cast(dict[str, dict[str, object]], defs.get("tire_setups", {}))
        ref_key = cast(str, tires.pop("default_ref"))
        inline_default = copy.deepcopy(ts[ref_key])

    definitions = cast(dict[str, object], fixture.setdefault("definitions", {}))
    tire_setups = cast(dict[str, dict[str, object]], definitions.setdefault("tire_setups", {}))
    tire_setups["test_default_setup"] = inline_default
    tires["default_ref"] = "test_default_setup"

    _write_shard(tmp_path, relative_path, fixture)
    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()

    target = next(config for config in loaded if config.id == target_row["id"])
    assert target.default_tire.width_mm == float(
        cast(dict[str, object], inline_default["front"])["width_mm"]  # type: ignore[arg-type]
    )


def test_load_vehicle_configurations_expands_option_setup_ref(tmp_path: Path) -> None:
    """Loader must expand ``setup_ref`` inside a tire option entry."""

    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    target_row = rows[0]
    tires = cast(dict[str, object], target_row["tires"])

    setup_block: dict[str, object] = {
        "confidence": "official_exact",
        "front": {"width_mm": 245.0, "aspect_pct": 35.0, "rim_in": 19.0},
        "rear": {"width_mm": 275.0, "aspect_pct": 30.0, "rim_in": 19.0},
        "default_axle_for_speed": "rear",
        "evidence_refs": ["secondary_technical_sources:carfolio-audi-a3-saloon-8v"],
    }
    definitions = cast(dict[str, object], fixture.setdefault("definitions", {}))
    tire_setups = cast(dict[str, dict[str, object]], definitions.setdefault("tire_setups", {}))
    tire_setups["test_option_setup"] = setup_block

    options = cast(list[dict[str, object]], tires.setdefault("options", []))
    options.append({"name": "Test Option 19", "setup_ref": "test_option_setup"})

    _write_shard(tmp_path, relative_path, fixture)
    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()

    target = next(config for config in loaded if config.id == target_row["id"])
    matched = [opt for opt in target.tire_options if opt.name == "Test Option 19"]
    assert len(matched) == 1
    assert matched[0].tire_setup.front.width_mm == 245.0
    assert matched[0].tire_setup.rear.rim_in == 19.0


def test_load_vehicle_configurations_fails_closed_for_unknown_default_ref(
    tmp_path: Path,
) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    tires = cast(dict[str, object], rows[0]["tires"])
    tires.pop("default", None)
    tires["default_ref"] = "does_not_exist"
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_fails_closed_for_unknown_setup_ref(
    tmp_path: Path,
) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    tires = cast(dict[str, object], rows[0]["tires"])
    options = cast(list[dict[str, object]], tires.setdefault("options", []))
    options.append({"name": "Bad Option", "setup_ref": "does_not_exist"})
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []


def test_load_vehicle_configurations_derives_order_analysis_policy_when_no_override(
    tmp_path: Path,
) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    rows[0].pop("order_analysis_policy_override", None)
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()
    assert loaded
    config = loaded[0]
    assert config.order_analysis_policy.usable_for_wheel_order is True
    assert config.order_analysis_policy.requires_manual_confirmation is True


def test_load_vehicle_configurations_applies_order_analysis_policy_override(
    tmp_path: Path,
) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    rows[0]["order_analysis_policy_override"] = {
        "reason": "row-marked-not-ready-for-wheel-order",
        "usable_for_wheel_order": False,
    }
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        loaded = load_vehicle_configurations()
    assert loaded
    assert loaded[0].order_analysis_policy.usable_for_wheel_order is False


def test_load_vehicle_configurations_fails_closed_for_unknown_override_field(
    tmp_path: Path,
) -> None:
    relative_path, shard = _load_sample_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    rows[0]["order_analysis_policy_override"] = {
        "reason": "broken",
        "bogus_field": True,
    }
    _write_shard(tmp_path, relative_path, fixture)

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_DIR",
        tmp_path,
    ):
        assert load_vehicle_configurations() == []
