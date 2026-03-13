"""Sensor identity and mounting-position domain objects.

``SensorPlacement`` is a sensor's mounting position on the vehicle, owning
position category classification (wheel, drivetrain, body).

``Sensor`` is a physical accelerometer node, owning identity, user-assigned
name, and its optional placement.
"""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.locations import WHEEL_LOCATION_CODES

__all__ = [
    "Sensor",
    "SensorPlacement",
]


@dataclass(frozen=True, slots=True)
class SensorPlacement:
    """A sensor's mounting position on the vehicle.

    Replaces stringly-typed location handling with a first-class value
    object that carries identity, classification, and display helpers.

    ``code`` is the canonical location code (e.g. ``"front_left_wheel"``).
    ``label`` is the human-readable display name (e.g. ``"Front Left Wheel"``).
    """

    code: str
    label: str = ""

    # -- classification ----------------------------------------------------

    _WHEEL_CODES: frozenset[str] = WHEEL_LOCATION_CODES

    _DRIVETRAIN_CODES: frozenset[str] = frozenset(
        {
            "transmission",
            "driveshaft_tunnel",
        },
    )

    _BODY_CODES: frozenset[str] = frozenset(
        {
            "driver_seat",
            "front_passenger_seat",
            "rear_left_seat",
            "rear_center_seat",
            "rear_right_seat",
            "trunk",
        },
    )

    @property
    def is_wheel(self) -> bool:
        """Whether this placement is on a wheel/corner position."""
        return self.code in self._WHEEL_CODES

    @property
    def is_drivetrain(self) -> bool:
        """Whether this placement is on a drivetrain component."""
        return self.code in self._DRIVETRAIN_CODES

    @property
    def is_body(self) -> bool:
        """Whether this placement is on a body/cabin position."""
        return self.code in self._BODY_CODES

    @property
    def position_category(self) -> str:
        """Return a broad category: ``'wheel'``, ``'drivetrain'``, ``'body'``, or ``'other'``."""
        if self.is_wheel:
            return "wheel"
        if self.is_drivetrain:
            return "drivetrain"
        if self.is_body:
            return "body"
        return "other"

    @property
    def display_name(self) -> str:
        """Human-readable name, falling back to the code if no label is set."""
        return self.label or self.code.replace("_", " ").title()

    # -- factory methods ---------------------------------------------------

    @classmethod
    def from_code(cls, code: str) -> SensorPlacement:
        """Create a placement from a canonical location code.

        Resolves the human-readable label from the location code registry
        (``vibesensor.locations.LOCATION_CODES``).  Falls back to a
        title-cased version of the code if the code is not found.
        """
        from vibesensor.locations import LOCATION_CODES

        label = LOCATION_CODES.get(code, code.replace("_", " ").title())
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
