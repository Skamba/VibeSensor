"""Shared contract constants — single source of truth for Python consumers.

These constants were formerly loaded at runtime from JSON files via
``vibesensor_shared.contracts``.  They are static values that never change
between deployments, so inline Python constants are simpler and faster.
"""

from __future__ import annotations

from typing import Final

NETWORK_PORTS: Final[dict[str, int]] = {
    "server_udp_data": 9000,
    "server_udp_control": 9001,
    "firmware_control_port_base": 9010,
}

LOCATION_CODES: Final[dict[str, str]] = {
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
