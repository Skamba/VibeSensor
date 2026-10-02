from __future__ import annotations

from vibesensor.adapters.http.settings.preferences import (
    language_response_payload,
    speed_unit_response_payload,
)
from vibesensor.adapters.http.settings.speed_source import (
    speed_source_response_payload,
    speed_source_update_payload_from_mapping,
)
from vibesensor.domain.speed_source import SpeedSourceKind


def test_speed_source_update_payload_from_mapping_projects_http_keys() -> None:
    payload = speed_source_update_payload_from_mapping(
        {
            "speed_source": SpeedSourceKind.OBD2,
            "manual_speed_kph": 45.0,
            "stale_timeout_s": 9.0,
            "obd_device_mac": "AA:BB:CC:DD:EE:FF",
        }
    )

    assert payload == {
        "speedSource": SpeedSourceKind.OBD2,
        "manualSpeedKph": 45.0,
        "staleTimeoutS": 9.0,
        "obdDeviceMac": "AA:BB:CC:DD:EE:FF",
    }


def test_speed_source_response_payload_projects_internal_keys() -> None:
    payload = speed_source_response_payload(
        {
            "speedSource": SpeedSourceKind.GPS,
            "manualSpeedKph": None,
            "staleTimeoutS": 10.0,
            "obdDeviceMac": None,
            "obdDeviceName": None,
        }
    )

    assert payload == {
        "speed_source": SpeedSourceKind.GPS,
        "manual_speed_kph": None,
        "stale_timeout_s": 10.0,
        "obd_device_mac": None,
        "obd_device_name": None,
    }


def test_preference_response_payloads_project_scalars() -> None:
    assert language_response_payload("nl") == {"language": "nl"}
    assert speed_unit_response_payload("mps") == {"speed_unit": "mps"}
