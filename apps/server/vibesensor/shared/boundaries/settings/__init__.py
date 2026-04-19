"""Canonical boundary package for shared settings payload adapters."""

from .analysis import (
    analysis_settings_response_payload,
    analysis_settings_update_payload_from_mapping,
)
from .cars import car_config_update_payload_from_mapping, cars_response_payload
from .preferences import language_response_payload, speed_unit_response_payload
from .snapshot import (
    coerce_language_code,
    coerce_speed_unit_code,
    settings_snapshot_from_payload,
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
    "car_config_update_payload_from_mapping",
    "cars_response_payload",
    "coerce_language_code",
    "coerce_speed_unit_code",
    "language_response_payload",
    "settings_snapshot_from_payload",
    "speed_source_response_payload",
    "speed_source_update_payload_from_mapping",
    "speed_unit_response_payload",
    "validated_language_code",
    "validated_speed_unit_code",
]
