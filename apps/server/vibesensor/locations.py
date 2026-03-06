"""Sensor location helpers — codes, labels, and wheel-location tests.

Maps short sensor location codes (e.g. ``"fl"``, ``"rr"``) to human-readable
labels and provides helpers to identify wheel-mounted sensor positions.
"""

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
# than a canonical location code.  Pre-normalised (hyphens → spaces) so
# is_wheel_location() needs no per-call normalisation of these tokens.
_WHEEL_LABEL_TOKENS: tuple[str, ...] = (
    "front left",
    "front right",
    "rear left",
    "rear right",
    "fl wheel",
    "fr wheel",
    "rl wheel",
    "rr wheel",
)

# Labels that exclude a sensor from wheel/corner classification.
_NON_WHEEL_TOKENS: tuple[str, ...] = (
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


def is_wheel_location(label_or_code: str) -> bool:
    """Return True if *label_or_code* identifies a wheel/corner sensor.

    Accepts both canonical codes (``front_left_wheel``) and human-readable
    labels (``Front Left``, ``front-right``).  The check is case-insensitive.
    """
    if not label_or_code:
        return False
    normalised = label_or_code.strip().lower().replace("_", " ").replace("-", " ")
    if any(tok in normalised for tok in _NON_WHEEL_TOKENS):
        return False
    if normalised.replace(" ", "_") in WHEEL_LOCATION_CODES:
        return True
    for token in _WHEEL_LABEL_TOKENS:
        if (
            token == normalised
            or normalised.startswith(token + " ")
            or normalised == token + " wheel"
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
    """Return all known sensor location options as a list of ``{code, label}`` dicts."""
    return [{"code": code, "label": label} for code, label in LOCATION_OPTIONS]


def label_for_code(code: str) -> str | None:
    """Return the human-readable label for location *code*, or ``None`` if unknown."""
    return LOCATION_LABEL_BY_CODE.get(code)
