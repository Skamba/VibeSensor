"""Shared sensor-configuration contracts and helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict

__all__ = [
    "SensorConfig",
    "SensorConfigPayload",
    "SensorsByMacPayload",
]


class SensorConfigPayload(TypedDict):
    name: str
    location_code: str


type SensorsByMacPayload = dict[str, SensorConfigPayload]


@dataclass(slots=True)
class SensorConfig:
    """Persisted configuration for a sensor node (ID, name, location_code)."""

    sensor_id: str
    name: str
    location_code: str

    @classmethod
    def from_dict(cls, sensor_id: str, data: Mapping[str, object]) -> SensorConfig:
        """Construct a :class:`SensorConfig` from *sensor_id* and a raw dict."""
        name = str(data.get("name") or sensor_id).strip()[:64]
        location_code = str(data.get("location_code") or "").strip()[:64]
        return cls(
            sensor_id=sensor_id,
            name=name or sensor_id,
            location_code=location_code,
        )

    def to_dict(self) -> SensorConfigPayload:
        """Serialize this sensor config to a plain dict."""
        return {"name": self.name, "location_code": self.location_code}
