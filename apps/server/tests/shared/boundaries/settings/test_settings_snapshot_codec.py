from __future__ import annotations

import json

from vibesensor.shared.boundaries.settings.snapshot import (
    settings_snapshot_from_json,
    settings_snapshot_from_payload,
    settings_snapshot_to_json,
)


def test_settings_snapshot_json_round_trip_preserves_canonical_payload() -> None:
    payload = {
        "cars": [
            {
                "id": "car-1",
                "name": "Test Car",
                "type": "suv",
                "aspects": {"tire_width_mm": 255.0},
                "variant": "sport",
            }
        ],
        "activeCarId": "car-1",
        "speedSource": "obd2",
        "manualSpeedKph": 60.0,
        "staleTimeoutS": 12.0,
        "obdDeviceMac": "00043e5a4a4d",
        "obdDeviceName": "OBDLink MX+",
        "language": "nl",
        "speedUnit": "mps",
        "sensorsByMac": {
            "112233445566": {
                "name": "Rear Left Wheel",
                "location_code": "rear_left_wheel",
            }
        },
    }

    encoded = settings_snapshot_to_json(payload)

    assert settings_snapshot_from_json(encoded) == settings_snapshot_from_payload(payload)


def test_settings_snapshot_from_json_normalizes_legacy_values() -> None:
    raw = json.dumps(
        {
            "cars": [
                {
                    "id": "",
                    "name": "  Legacy Car  ",
                    "type": "  coupe  ",
                    "aspects": {"tire_width_mm": 245},
                    "variant": "",
                }
            ],
            "activeCarId": "missing-car",
            "speedSource": "manual",
            "manualSpeedKph": "80",
            "staleTimeoutS": "17",
            "obdDeviceMac": "00:04:3E:5A:4A:4D",
            "obdDeviceName": "  OBDLink MX+  ",
            "language": " NL ",
            "speedUnit": " MPS ",
            "sensorsByMac": {
                "11:22:33:44:55:66": {
                    "name": "Rear Left Wheel",
                    "location_code": "rear_left_wheel",
                },
                "bad-mac": {"name": "bad", "location_code": "rear_right_wheel"},
            },
        }
    )

    payload = settings_snapshot_from_json(raw)

    assert payload is not None
    assert len(payload["cars"]) == 1
    assert payload["cars"][0]["name"] == "Legacy Car"
    assert payload["cars"][0]["type"] == "coupe"
    assert "variant" not in payload["cars"][0]
    assert payload["activeCarId"] is None
    assert payload["speedSource"] == "manual"
    assert payload["manualSpeedKph"] is None
    assert payload["staleTimeoutS"] == 10.0
    assert payload["obdDeviceMac"] == "00043e5a4a4d"
    assert payload["obdDeviceName"] == "OBDLink MX+"
    assert payload["language"] == "nl"
    assert payload["speedUnit"] == "mps"
    assert set(payload["sensorsByMac"]) == {"112233445566"}


def test_settings_snapshot_from_json_returns_none_for_invalid_json() -> None:
    assert settings_snapshot_from_json("not-valid-json{{{") is None
