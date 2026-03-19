"""Sensor identity and mounting-position domain objects.

``SensorPlacement`` is a sensor's mounting position on the vehicle.

``Sensor`` is a physical accelerometer node, owning identity, user-assigned
name, and its optional placement.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

__all__ = [
    "Sensor",
    "SensorPlacement",
    "normalize_sensor_id",
]

# Domain-internal location code registry.  The canonical external-facing
# copy lives in ``shared/locations.py``; a hygiene test guards parity.
_LOCATION_CODES: Final[dict[str, str]] = {
    "front_left_wheel": "Front Left Wheel",
    "front_right_wheel": "Front Right Wheel",
    "rear_left_wheel": "Rear Left Wheel",
    "rear_right_wheel": "Rear Right Wheel",
    "transmission": "Transmission",
    "driveshaft_tunnel": "Driveshaft Tunnel",
    "engine_bay": "Engine Bay",
    "front_subframe": "Front Subframe",
    "rear_subframe": "Rear Subframe",
    "driver_seat": "Driver Seat",
    "front_passenger_seat": "Front Passenger Seat",
    "rear_left_seat": "Rear Left Seat",
    "rear_center_seat": "Rear Center Seat",
    "rear_right_seat": "Rear Right Seat",
    "trunk": "Trunk",
}


@dataclass(frozen=True, slots=True)
class SensorPlacement:
    """A sensor's mounting position on the vehicle.

    ``code`` is the canonical location code (e.g. ``"front_left_wheel"``).
    ``label`` is the human-readable display name (e.g. ``"Front Left Wheel"``).
    """

    code: str
    label: str = ""

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("SensorPlacement.code must be a non-empty string")

    @property
    def display_name(self) -> str:
        """Human-readable name, falling back to the code if no label is set."""
        return self.label or self.code.replace("_", " ").title()

    # -- factory methods ---------------------------------------------------

    @classmethod
    def from_code(cls, code: str) -> SensorPlacement:
        """Create a placement from a canonical location code.

        Resolves the human-readable label from the domain-internal location
        code registry.  Falls back to a title-cased version of the code if
        the code is not found.
        """
        label = _LOCATION_CODES.get(code, code.replace("_", " ").title())
        return cls(code=code, label=label)


@dataclass(frozen=True, slots=True)
class Sensor:
    """A physical accelerometer node attached to the vehicle.

    Owns identity (MAC-based ``sensor_id``), user-assigned name, and
    the placement where the sensor is mounted.  Configuration and
    persistence details remain in ``SensorConfig``.
    """

    sensor_id: str
    name: str = ""
    placement: SensorPlacement | None = None

    # -- queries -----------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Human-readable sensor name, falling back to sensor_id."""
        return self.name or self.sensor_id

    @property
    def location_code(self) -> str:
        """Shortcut to the placement code, or empty string if unplaced."""
        return self.placement.code if self.placement else ""

    @property
    def is_placed(self) -> bool:
        """Whether this sensor has an assigned placement."""
        return self.placement is not None and bool(self.placement.code)

    # -- factory methods ---------------------------------------------------

    @classmethod
    def from_location_codes(cls, location_codes: Sequence[str]) -> tuple[Sensor, ...]:
        """Build sensors from location codes available during analysis."""
        return tuple(
            cls(
                sensor_id=code,
                placement=SensorPlacement.from_code(code),
            )
            for code in location_codes
        )


# ---------------------------------------------------------------------------
# Sensor ID normalisation
# ---------------------------------------------------------------------------

_SENSOR_ID_HEX_LEN: Final[int] = 12


def normalize_sensor_id(sensor_id: str) -> str:
    """Normalize a sensor MAC / hex string to canonical 12-char lowercase hex.

    Accepts raw hex (``"AABBCCDDEEFF"``) or colon-separated
    (``"AA:BB:CC:DD:EE:FF"``) formats.
    """
    compact = sensor_id.replace(":", "").strip().lower()
    if len(compact) != _SENSOR_ID_HEX_LEN:
        raise ValueError("sensor_id must be 12 hex chars")
    # Validate hex by attempting conversion.
    bytes.fromhex(compact)
    return compact
