from __future__ import annotations

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


def all_locations() -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in LOCATION_OPTIONS]


def label_for_code(code: str) -> str | None:
    return LOCATION_LABEL_BY_CODE.get(code)

