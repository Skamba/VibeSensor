"""Focused validation checks for source-registry loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.car_library_source_evidence import load_car_source_registry


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
