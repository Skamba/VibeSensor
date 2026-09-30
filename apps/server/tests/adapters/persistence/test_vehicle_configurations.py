from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from test_support.car_library_validation.source_evidence import (
    load_car_source_registry,
    validate_vehicle_configuration_source_evidence,
)
from test_support.vehicle_configuration_shards import (
    load_sample_vehicle_configuration_shards,
    write_vehicle_configuration_shard,
)

from vibesensor.adapters.persistence.vehicle_configurations import load_vehicle_configurations


def _load_configs_from_data_dir(data_dir: Path):
    return load_vehicle_configurations(data_dir=data_dir)


def test_load_vehicle_configurations_reads_multiple_shards(tmp_path: Path) -> None:
    sample_shards = load_sample_vehicle_configuration_shards(2)
    expected_ids = {
        str(row["id"])
        for _, shard in sample_shards
        for row in cast(list[dict[str, object]], shard["configurations"])
    }
    for relative_path, shard in sample_shards:
        write_vehicle_configuration_shard(tmp_path, relative_path, shard)

    loaded = _load_configs_from_data_dir(tmp_path)

    assert {config.id for config in loaded} == expected_ids


def test_load_vehicle_configurations_fails_closed_for_duplicate_ids_across_shards(
    tmp_path: Path,
) -> None:
    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    duplicate = copy.deepcopy(shard)
    write_vehicle_configuration_shard(tmp_path, relative_path, duplicate)
    write_vehicle_configuration_shard(tmp_path, Path("duplicate") / relative_path.name, duplicate)

    assert _load_configs_from_data_dir(tmp_path) == []


def test_load_vehicle_configurations_fails_closed_for_invalid_shard(tmp_path: Path) -> None:
    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    write_vehicle_configuration_shard(tmp_path, relative_path, shard)
    bad_path = tmp_path / "broken" / "bad.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{not valid json", encoding="utf-8")

    assert _load_configs_from_data_dir(tmp_path) == []


def test_source_evidence_validation_flags_loaded_rows_missing_required_evidence_refs(
    tmp_path: Path,
) -> None:
    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    bad_payload = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], bad_payload["configurations"])
    bad_drivetrain = cast(dict[str, object], rows[0]["drivetrain"])
    rows[0]["drivetrain"] = {
        "value": bad_drivetrain["value"],
        "confidence": "official_exact",
        "notes": "Broken test payload without evidence refs.",
    }
    write_vehicle_configuration_shard(tmp_path, relative_path, bad_payload)

    issues = validate_vehicle_configuration_source_evidence(
        _load_configs_from_data_dir(tmp_path),
        registry=load_car_source_registry(),
    )

    assert [issue.rule for issue in issues] == ["missing_required_evidence_refs"]


def test_load_vehicle_configurations_expands_notes_and_evidence_refs(tmp_path: Path) -> None:
    """Loader must inline shard-local notes_ref and evidence_refs_ref values."""

    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
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

    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)
    loaded = _load_configs_from_data_dir(tmp_path)

    target = next(config for config in loaded if config.id == rows[0]["id"])
    assert target.drivetrain_metadata.notes == notes_text
    assert target.drivetrain_metadata.evidence_refs == tuple(evidence_list)


def test_load_vehicle_configurations_rejects_legacy_array_shard(tmp_path: Path) -> None:
    """Bare array shards are no longer accepted; canonical shape is the shard object."""

    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    legacy_path = tmp_path / relative_path
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(json.dumps(shard["configurations"], indent=2) + "\n", encoding="utf-8")

    assert _load_configs_from_data_dir(tmp_path) == []


def test_load_vehicle_configurations_applies_shard_defaults(tmp_path: Path) -> None:
    """Top-level ``defaults`` merge into rows that lack the field."""

    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    defaults = cast(dict[str, object], fixture.setdefault("defaults", {}))
    expected_brand = defaults["brand"] if "brand" in defaults else rows[0]["brand"]
    for row in rows:
        row.pop("brand", None)
    defaults["brand"] = expected_brand
    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)

    loaded = _load_configs_from_data_dir(tmp_path)

    assert loaded
    assert all(config.brand == expected_brand for config in loaded)


def test_load_vehicle_configurations_row_overrides_default(tmp_path: Path) -> None:
    """Row-level keys override shard defaults for that row only."""

    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    assert len(rows) >= 1
    defaults = cast(dict[str, object], fixture.setdefault("defaults", {}))
    defaults["brand"] = "DEFAULT_BRAND"
    overridden_id = str(rows[0]["id"])
    rows[0]["brand"] = "ROW_BRAND"
    for row in rows[1:]:
        row.pop("brand", None)
    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)

    loaded = _load_configs_from_data_dir(tmp_path)

    by_id = {config.id: config for config in loaded}
    assert by_id[overridden_id].brand == "ROW_BRAND"
    for config_id, config in by_id.items():
        if config_id != overridden_id:
            assert config.brand == "DEFAULT_BRAND"


def test_load_vehicle_configurations_expands_default_tire_setup_ref(tmp_path: Path) -> None:
    """Loader must expand ``tires.default_ref`` from ``definitions.tire_setups``."""

    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
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

    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)
    loaded = _load_configs_from_data_dir(tmp_path)

    target = next(config for config in loaded if config.id == target_row["id"])
    assert target.default_tire.width_mm == float(
        cast(dict[str, object], inline_default["front"])["width_mm"]  # type: ignore[arg-type]
    )


def test_load_vehicle_configurations_expands_option_setup_ref(tmp_path: Path) -> None:
    """Loader must expand ``setup_ref`` inside a tire option entry."""

    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
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

    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)
    loaded = _load_configs_from_data_dir(tmp_path)

    target = next(config for config in loaded if config.id == target_row["id"])
    matched = [opt for opt in target.tire_options if opt.name == "Test Option 19"]
    assert len(matched) == 1
    assert matched[0].tire_setup.front.width_mm == 245.0
    assert matched[0].tire_setup.rear.rim_in == 19.0


def test_load_vehicle_configurations_derives_order_analysis_policy_when_no_override(
    tmp_path: Path,
) -> None:
    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    rows[0].pop("order_analysis_policy_override", None)
    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)

    loaded = _load_configs_from_data_dir(tmp_path)
    assert loaded
    config = loaded[0]
    assert config.order_analysis_policy.usable_for_wheel_order is True
    assert config.order_analysis_policy.requires_manual_confirmation is True


def test_load_vehicle_configurations_applies_order_analysis_policy_override(
    tmp_path: Path,
) -> None:
    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    fixture = copy.deepcopy(shard)
    rows = cast(list[dict[str, object]], fixture["configurations"])
    rows[0]["order_analysis_policy_override"] = {
        "reason": "row-marked-not-ready-for-wheel-order",
        "usable_for_wheel_order": False,
    }
    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)

    loaded = _load_configs_from_data_dir(tmp_path)
    assert loaded
    assert loaded[0].order_analysis_policy.usable_for_wheel_order is False


def _first_row(shard: dict[str, object]) -> dict[str, object]:
    return cast(list[dict[str, object]], shard["configurations"])[0]


def _row_section(shard: dict[str, object], section: str) -> dict[str, object]:
    return cast(dict[str, object], _first_row(shard)[section])


def _unknown_notes_ref(shard: dict[str, object]) -> None:
    drivetrain = _row_section(shard, "drivetrain")
    drivetrain.pop("notes", None)
    drivetrain["notes_ref"] = "does_not_exist"


def _unknown_evidence_refs_ref(shard: dict[str, object]) -> None:
    drivetrain = _row_section(shard, "drivetrain")
    drivetrain.pop("evidence_refs", None)
    drivetrain["evidence_refs_ref"] = "does_not_exist"


def _defaults_miss_required_brand(shard: dict[str, object]) -> None:
    cast(dict[str, object], shard.setdefault("defaults", {})).pop("brand", None)
    for row in cast(list[dict[str, object]], shard["configurations"]):
        row.pop("brand", None)


def _unknown_default_ref(shard: dict[str, object]) -> None:
    tires = _row_section(shard, "tires")
    tires.pop("default", None)
    tires["default_ref"] = "does_not_exist"


def _unknown_setup_ref(shard: dict[str, object]) -> None:
    tires = _row_section(shard, "tires")
    options = cast(list[dict[str, object]], tires.setdefault("options", []))
    options.append({"name": "Bad Option", "setup_ref": "does_not_exist"})


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_unknown_notes_ref, id="unknown-notes-ref"),
        pytest.param(_unknown_evidence_refs_ref, id="unknown-evidence-refs-ref"),
        pytest.param(_defaults_miss_required_brand, id="defaults-miss-required-field"),
        pytest.param(
            lambda shard: shard.__setitem__("unexpected", {"brand": "X"}),
            id="unknown-top-level-key",
        ),
        pytest.param(_unknown_default_ref, id="unknown-default-tire-ref"),
        pytest.param(_unknown_setup_ref, id="unknown-option-setup-ref"),
        pytest.param(
            lambda shard: _row_section(shard, "tires").__setitem__(
                "default_ref", "conflicting_default"
            ),
            id="tires-with-default-and-default-ref",
        ),
        pytest.param(
            lambda shard: _row_section(shard, "drivetrain").__setitem__("value", "BOGUS"),
            id="bad-drivetrain-value",
        ),
        pytest.param(
            lambda shard: _first_row(shard).__setitem__(
                "order_analysis_policy_override", {"reason": "broken", "bogus_field": True}
            ),
            id="unknown-override-field",
        ),
        pytest.param(
            lambda shard: _first_row(shard).__setitem__(
                "order_analysis_policy_override", {"usable_for_wheel_order": False}
            ),
            id="override-without-reason",
        ),
    ],
)
def test_load_vehicle_configurations_fails_closed_for_invalid_shard_content(
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    relative_path, shard = load_sample_vehicle_configuration_shards(1)[0]
    fixture = copy.deepcopy(shard)
    mutate(fixture)
    write_vehicle_configuration_shard(tmp_path, relative_path, fixture)

    assert _load_configs_from_data_dir(tmp_path) == []
