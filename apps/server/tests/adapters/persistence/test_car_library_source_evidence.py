"""Regression coverage for canonical vehicle source evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.car_library_source_evidence import (
    load_car_source_registry,
    validate_vehicle_configuration_source_evidence,
)
from vibesensor.adapters.persistence.vehicle_configurations import load_vehicle_configurations
from vibesensor.domain import VehicleConfigurationIssue, VehicleConfigurationNote


def _config_for(model_name: str, variant_name: str):
    for config in load_vehicle_configurations():
        if config.model_name == model_name and config.variant_name == variant_name:
            return config
    raise AssertionError(f"Vehicle configuration not found: {model_name} / {variant_name}")


def _metadata_refs(config, field_name: str) -> tuple[str, ...]:
    metadata = config.metadata_for(field_name)
    return metadata.evidence_refs if metadata is not None else ()


def test_current_car_source_registry_covers_current_vehicle_evidence_refs() -> None:
    registry = load_car_source_registry()
    configs = load_vehicle_configurations()

    assert validate_vehicle_configuration_source_evidence(configs, registry=registry) == ()
    referenced_source_ids = {
        ref
        for config in configs
        for field_name in config.coverage_policy_fields
        for ref in _metadata_refs(config, field_name)
    }
    referenced_source_ids.update(
        ref
        for config in configs
        for ref in (
            config.gear_ratios_metadata.evidence_refs if config.gear_ratios_metadata else ()
        )
    )
    referenced_source_ids.update(
        ref
        for config in configs
        for option in config.tire_options
        for ref in (option.metadata.evidence_refs if option.metadata else ())
    )
    referenced_source_ids.update(
        ref
        for config in configs
        for note in config.verification_notes
        for ref in note.evidence_refs
    )
    referenced_source_ids.update(
        ref for config in configs for issue in config.unresolved for ref in issue.evidence_refs
    )
    assert referenced_source_ids <= set(registry.sources)


def test_validate_vehicle_configuration_source_evidence_flags_missing_required_evidence_refs() -> (
    None
):
    config = _config_for("3 Series (G20, 2019-2025)", "330i xDrive")
    broken = replace(
        config,
        drivetrain_metadata=replace(config.drivetrain_metadata, evidence_refs=()),
    )

    issues = validate_vehicle_configuration_source_evidence(
        [broken],
        registry=load_car_source_registry(),
    )

    assert [issue.rule for issue in issues] == ["missing_required_evidence_refs"]
    assert "drivetrain" in issues[0].message


def test_validate_vehicle_configuration_source_evidence_flags_unknown_note_reference() -> None:
    config = _config_for("2 Series Active Tourer (F45, 2018)", "220i")
    broken = replace(
        config,
        verification_notes=(
            VehicleConfigurationNote(
                note="Broken verification note",
                evidence_refs=("demo_pack:missing-source",),
            ),
        ),
    )

    issues = validate_vehicle_configuration_source_evidence(
        [broken],
        registry=load_car_source_registry(),
    )

    assert [issue.rule for issue in issues] == ["missing_source_reference"]
    assert "verification note references unknown source" in issues[0].message


def test_validate_vehicle_configuration_source_evidence_flags_unknown_unresolved_reference() -> (
    None
):
    config = _config_for("5 Series (G60, 2024-2026)", "i5 eDrive40")
    broken = replace(
        config,
        unresolved=(
            VehicleConfigurationIssue(
                item="Broken unresolved item",
                reason="Test only",
                evidence_refs=("demo_pack:missing-source",),
            ),
        ),
    )

    issues = validate_vehicle_configuration_source_evidence(
        [broken],
        registry=load_car_source_registry(),
    )

    assert [issue.rule for issue in issues] == ["missing_source_reference"]
    assert "unresolved item references unknown source" in issues[0].message


def test_load_car_source_registry_rejects_bad_source_pack_reference(tmp_path: Path) -> None:
    source_dir = tmp_path / "car_sources"
    source_dir.mkdir()
    (source_dir / "demo_pack.json").write_text(
        json.dumps(
            {
                "pack_id": "demo_pack",
                "sources": [
                    {
                        "id": "wrong_pack:known-source",
                        "url": "https://example.com/source",
                        "title": "Known source",
                        "note": "Machine-checkable demo source.",
                        "confidence": "high",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must start with"):
        load_car_source_registry(source_packs_dir=source_dir)
