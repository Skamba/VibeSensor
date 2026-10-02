from __future__ import annotations

import json

from vibesensor.settings.snapshot_codec import (
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
        "obdDeviceMac": "02000000004d",
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


def test_settings_snapshot_json_round_trip_keeps_order_reference_status_and_axle() -> None:
    car = {
        "id": "car-1",
        "name": "Staggered",
        "type": "coupe",
        "aspects": {
            "front_tire_width_mm": 225.0,
            "rear_tire_width_mm": 255.0,
            "default_axle_for_speed": "front",
        },
        "order_reference_status": {
            "selection_source_status": "exact_row",
            "requires_manual_confirmation": True,
            "tire_dimensions_confidence": "official_exact",
            "transmission_name": "6MT",
            "transmission_confidence": "family_default",
        },
    }
    payload = {
        "cars": [car],
        "activeCarId": "car-1",
        "speedSource": "gps",
        "manualSpeedKph": None,
        "staleTimeoutS": 10.0,
        "language": "en",
        "speedUnit": "kmh",
        "sensorsByMac": {},
    }

    decoded = settings_snapshot_from_json(settings_snapshot_to_json(payload))

    assert decoded is not None
    assert decoded["cars"] == [car]


def test_settings_snapshot_from_json_decodes_snapshot_written_by_previous_encoder() -> None:
    """Snapshots written before the car shape was shared (explicit null variant) still load."""

    raw = (
        '{"cars":[{"id":"car-1","name":"Daily","type":"wagon","aspects":'
        '{"tire_width_mm":225.0,"rim_in":17.0,"final_drive_ratio":3.5},"variant":null}],'
        '"activeCarId":"car-1","speedSource":"gps","manualSpeedKph":null,"staleTimeoutS":10.0,'
        '"obdDeviceMac":null,"obdDeviceName":null,"language":"en","speedUnit":"kmh",'
        '"sensorsByMac":{"112233445566":{"name":"Rear Left","location_code":"rear_left_wheel"}}}'
    )

    decoded = settings_snapshot_from_json(raw)

    assert decoded is not None
    assert decoded["cars"] == [
        {
            "id": "car-1",
            "name": "Daily",
            "type": "wagon",
            "aspects": {"tire_width_mm": 225.0, "rim_in": 17.0, "final_drive_ratio": 3.5},
            "variant": None,
        }
    ]
    assert decoded["activeCarId"] == "car-1"


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
            "obdDeviceMac": "02:00:00:00:00:4D",
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
