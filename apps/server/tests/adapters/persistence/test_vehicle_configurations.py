from __future__ import annotations

import json
from unittest.mock import patch

from vibesensor.adapters.persistence.vehicle_configurations import (
    _VEHICLE_CONFIG_DATA_FILE,
    load_vehicle_configurations,
)


def test_load_vehicle_configurations_fails_closed_when_required_evidence_refs_are_missing(
    tmp_path,
) -> None:
    bad_payload = json.loads(_VEHICLE_CONFIG_DATA_FILE.read_text(encoding="utf-8"))
    bad_payload[0]["drivetrain"] = {
        "value": bad_payload[0]["drivetrain"]["value"],
        "confidence": "official_exact",
        "notes": "Broken test payload without evidence refs.",
    }
    bad_path = tmp_path / "vehicle_configurations.json"
    bad_path.write_text(json.dumps(bad_payload), encoding="utf-8")

    with patch(
        "vibesensor.adapters.persistence.vehicle_configurations._VEHICLE_CONFIG_DATA_FILE",
        bad_path,
    ):
        assert load_vehicle_configurations() == []
