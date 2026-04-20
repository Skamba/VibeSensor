"""Canonical boundary package for shared settings payload adapters."""

from .analysis import (
    analysis_settings_response_payload,
    analysis_settings_update_payload_from_mapping,
)
from .cars import car_config_update_payload_from_mapping, cars_response_payload
from .preferences import language_response_payload, speed_unit_response_payload
from .snapshot import (
    CarConfigRecord,
    SettingsSnapshotRecord,
    settings_snapshot_from_json,
    settings_snapshot_to_json,
    validated_language_code,
    validated_speed_unit_code,
)
from .speed_source import (
    speed_source_response_payload,
    speed_source_update_payload_from_mapping,
)

__all__ = [
    "analysis_settings_response_payload",
    "analysis_settings_update_payload_from_mapping",
    "CarConfigRecord",
    "car_config_update_payload_from_mapping",
    "cars_response_payload",
    "SettingsSnapshotRecord",
    "settings_snapshot_from_json",
    "language_response_payload",
    "settings_snapshot_to_json",
    "speed_source_response_payload",
    "speed_source_update_payload_from_mapping",
    "speed_unit_response_payload",
    "validated_language_code",
    "validated_speed_unit_code",
]
