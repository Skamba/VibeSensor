from __future__ import annotations

import json

from vibesensor.shared.boundaries.settings.snapshot import (
    settings_snapshot_from_json,
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

    assert settings_snapshot_from_json(encoded) == payload


def test_settings_snapshot_from_json_rejects_legacy_values() -> None:
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

    assert settings_snapshot_from_json(raw) is None


def test_settings_snapshot_from_json_returns_none_for_invalid_json() -> None:
    assert settings_snapshot_from_json("not-valid-json{{{") is None
