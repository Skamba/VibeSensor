"""Regression coverage for machine-checkable car source evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.adapters.persistence.car_library import load_vehicle_configurations
from vibesensor.adapters.persistence.car_library_source_evidence import (
    _EVIDENCE_FILE,
    load_car_source_registry,
    validate_vehicle_configuration_source_evidence,
)


def _config_for(model_name: str, variant_name: str):
    for config in load_vehicle_configurations():
        if config.model_name == model_name and config.variant_name == variant_name:
            return config
    raise AssertionError(f"Vehicle configuration not found: {model_name} / {variant_name}")


def test_current_car_source_registry_covers_current_exact_vehicle_source_ids() -> None:
    registry = load_car_source_registry()
    configs = load_vehicle_configurations()

    assert validate_vehicle_configuration_source_evidence(configs, registry=registry) == ()
    referenced_source_ids = {
        entry.source_id
        for config in configs
        for entry in config.field_provenance
        if entry.source_id is not None
    }
    assert referenced_source_ids == set(registry.evidence)


def test_validate_vehicle_configuration_source_evidence_flags_missing_required_source_id() -> None:
    config = _config_for("3 Series (G20, 2019-2025)", "330i xDrive")
    broken = replace(
        config,
        field_provenance=tuple(
            replace(entry, source_id=None) if entry.field_name == "drivetrain" else entry
            for entry in config.field_provenance
        ),
    )

    issues = validate_vehicle_configuration_source_evidence(
        [broken],
        registry=load_car_source_registry(),
    )

    assert [issue.rule for issue in issues] == ["missing_required_source_id"]
    assert "drivetrain" in issues[0].message


def test_load_car_source_registry_rejects_unknown_source_reference(tmp_path: Path) -> None:
    source_dir = tmp_path / "car_sources"
    source_dir.mkdir()
    (source_dir / "demo_pack.json").write_text(
        json.dumps(
            {
                "pack_id": "demo_pack",
                "sources": [
                    {
                        "id": "demo_pack:known-source",
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
    evidence_file = tmp_path / "car_library_evidence.json"
    evidence_file.write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "id": "demo:evidence",
                        "summary": "Broken evidence entry.",
                        "source_refs": ["demo_pack:missing-source"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="references unknown source"):
        load_car_source_registry(source_packs_dir=source_dir, evidence_file=evidence_file)


def test_load_vehicle_configurations_fails_closed_when_source_evidence_is_missing(
    tmp_path: Path,
) -> None:
    payload = json.loads(_EVIDENCE_FILE.read_text(encoding="utf-8"))
    payload["evidence"] = [
        row
        for row in payload["evidence"]
        if row["id"] != "variant_sources:BMW|3 Series (G20, 2019-2025):330i xDrive"
    ]
    bad_evidence_file = tmp_path / "car_library_evidence.json"
    bad_evidence_file.write_text(json.dumps(payload), encoding="utf-8")

    with patch(
        "vibesensor.adapters.persistence.car_library_source_evidence._EVIDENCE_FILE",
        bad_evidence_file,
    ):
        assert load_vehicle_configurations() == []
