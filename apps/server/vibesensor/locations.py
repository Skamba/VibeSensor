from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

LOCATION_OPTIONS: tuple[tuple[str, str], ...] = (
    ("front_left_wheel", "Front Left Wheel"),
    ("front_right_wheel", "Front Right Wheel"),
    ("rear_left_wheel", "Rear Left Wheel"),
    ("rear_right_wheel", "Rear Right Wheel"),
    ("transmission", "Transmission"),
    ("driveshaft_tunnel", "Driveshaft Tunnel"),
    ("engine_bay", "Engine Bay"),
    ("front_subframe", "Front Subframe"),
    ("rear_subframe", "Rear Subframe"),
    ("driver_seat", "Driver Seat"),
    ("front_passenger_seat", "Front Passenger Seat"),
    ("rear_left_seat", "Rear Left Seat"),
    ("rear_center_seat", "Rear Center Seat"),
    ("rear_right_seat", "Rear Right Seat"),
    ("trunk", "Trunk"),
)

LOCATION_LABEL_BY_CODE: dict[str, str] = dict(LOCATION_OPTIONS)

# ---------------------------------------------------------------------------
# Sensor-type classification
# ---------------------------------------------------------------------------
# Locations eligible as *fault sources* for wheel/tire diagnoses.
# Other sensors may detect transfer-path vibration but should not be
# reported as the fault origin for a wheel/corner diagnosis.
WHEEL_LOCATION_CODES: frozenset[str] = frozenset(
    {
        "front_left_wheel",
        "front_right_wheel",
        "rear_left_wheel",
        "rear_right_wheel",
    }
)

# Human-readable label substrings that identify a wheel/corner sensor.
# Used for fuzzy matching when the sample carries a display label rather
# than a canonical location code.
_WHEEL_LABEL_TOKENS: tuple[str, ...] = (
    "front left",
    "front right",
    "rear left",
    "rear right",
    "front-left",
    "front-right",
    "rear-left",
    "rear-right",
    "fl wheel",
    "fr wheel",
    "rl wheel",
    "rr wheel",
)


def is_wheel_location(label_or_code: str) -> bool:
    """Return True if *label_or_code* identifies a wheel/corner sensor.

    Accepts both canonical codes (``front_left_wheel``) and human-readable
    labels (``Front Left``, ``front-right``).  The check is case-insensitive.
    """
    if not label_or_code:
        return False
    normalised = label_or_code.strip().lower().replace("_", " ").replace("-", " ")
    # Reject labels containing seat/cabin/passenger identifiers
    _non_wheel_tokens = (
        "seat",
        "passenger",
        "cabin",
        "trunk",
        "engine",
        "subframe",
        "transmission",
        "driveshaft",
        "tunnel",
    )
    for exclude in _non_wheel_tokens:
        if exclude in normalised:
            return False
    if label_or_code.strip().lower().replace(" ", "_") in WHEEL_LOCATION_CODES:
        return True
    for token in _WHEEL_LABEL_TOKENS:
        token_norm = token.replace("-", " ")
        if (
            token_norm == normalised
            or normalised.startswith(token_norm + " ")
            or normalised == token_norm + " wheel"
        ):
            return True
    # Also match labels that end in "wheel" and start with a direction
    return "wheel" in normalised and any(
        normalised.startswith(d) for d in ("front", "rear", "fl", "fr", "rl", "rr")
    )


def has_any_wheel_location(locations: Iterable[str]) -> bool:
    """Return True if *locations* contains at least one wheel/corner sensor."""
    return any(is_wheel_location(loc) for loc in locations)


def all_locations() -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in LOCATION_OPTIONS]


def label_for_code(code: str) -> str | None:
    return LOCATION_LABEL_BY_CODE.get(code)
