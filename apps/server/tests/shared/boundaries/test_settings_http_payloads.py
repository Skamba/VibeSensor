from __future__ import annotations

from vibesensor.domain import AnalysisSettingsSnapshot, SpeedSourceKind
from vibesensor.shared.boundaries.settings import (
    analysis_settings_response_payload,
    analysis_settings_update_payload_from_mapping,
    car_config_update_payload_from_mapping,
    cars_response_payload,
    language_response_payload,
    speed_source_response_payload,
    speed_source_update_payload_from_mapping,
    speed_unit_response_payload,
)
from vibesensor.shared.types.car_config import CarsSnapshot


def test_car_config_update_payload_from_mapping_projects_fields() -> None:
    payload = car_config_update_payload_from_mapping(
        {
            "name": "GTI",
            "type": "hatchback",
            "aspects": {"tire_width_mm": 245.0},
        }
    )

    assert payload == {
        "name": "GTI",
        "type": "hatchback",
        "aspects": {"tire_width_mm": 245.0},
    }


def test_cars_response_payload_projects_snapshot() -> None:
    payload = cars_response_payload(
        CarsSnapshot(
            cars=[
                {
                    "id": "car-1",
                    "name": "Daily",
                    "type": "wagon",
                    "aspects": {"tire_width_mm": 225.0},
                    "variant": "sport",
                }
            ],
            active_car_id="car-1",
        )
    )

    assert payload == {
        "cars": [
            {
                "id": "car-1",
                "name": "Daily",
                "type": "wagon",
                "aspects": {"tire_width_mm": 225.0},
                "variant": "sport",
            }
        ],
        "active_car_id": "car-1",
    }


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


def test_analysis_settings_update_payload_from_mapping_omits_none_fields() -> None:
    payload = analysis_settings_update_payload_from_mapping(
        {
            "tire_width_mm": 255.0,
            "gear_uncertainty_pct": 1.5,
            "final_drive_ratio": None,
            "tire_aspect_pct": True,
        }
    )

    assert payload == {
        "tire_width_mm": 255.0,
        "gear_uncertainty_pct": 1.5,
    }


def test_analysis_settings_response_payload_projects_snapshot() -> None:
    payload = analysis_settings_response_payload(
        AnalysisSettingsSnapshot(
            tire_width_mm=255.0,
            tire_aspect_pct=40.0,
            rim_in=19.0,
        )
    )

    assert payload["tire_width_mm"] == 255.0
    assert payload["tire_aspect_pct"] == 40.0
    assert payload["rim_in"] == 19.0
    assert payload["final_drive_ratio"] == 0.0
