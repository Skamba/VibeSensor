"""Focused validation checks for source-registry loading."""

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


def test_validate_vehicle_source_evidence_requires_refs_for_official_metadata() -> None:
    config = load_vehicle_configurations()[0]
    broken = replace(
        config,
        drivetrain_metadata=replace(
            config.drivetrain_metadata,
            confidence="official_exact",
            evidence_refs=(),
        ),
    )

    issues = validate_vehicle_configuration_source_evidence(
        [broken],
        registry=load_car_source_registry(),
    )

    assert [issue.rule for issue in issues] == ["missing_required_evidence_refs"]
    assert "drivetrain" in issues[0].message


def test_validate_vehicle_configuration_source_evidence_rejects_unknown_ref() -> None:
    config = load_vehicle_configurations()[0]
    broken = replace(
        config,
        drivetrain_metadata=replace(
            config.drivetrain_metadata,
            evidence_refs=("missing_pack:missing-source",),
        ),
    )

    issues = validate_vehicle_configuration_source_evidence(
        [broken],
        registry=load_car_source_registry(),
    )

    assert [issue.rule for issue in issues] == ["missing_source_reference"]
    assert "missing_pack:missing-source" in issues[0].message
