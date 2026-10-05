"""The car's drive layout and the driveline facts that follow from it.

The owner gives one input, the layout (front-, rear- or all-wheel drive, or
not given). Everything the analysis needs is derived from it, so there is no
second input to contradict the first:

* the driven axles;
* which axle the saved final drive belongs to (always the driven one for FWD
  and RWD; for AWD only the car library knows, see
  ``VehicleConfiguration.driven_final_drive_axle``);
* whether the car has a propshaft. That assumes a front-engined car, which
  every car in the library is: FWD has none; RWD and AWD carry the engine's
  torque to the rear axle through one. An EV has none (each motor drives its
  axle directly), and neither has an e-AWD hybrid whose engine drives the
  front axle and an electric motor the rear (final drive on the front axle).

A dual-motor EV is modelled as AWD with the rear motor's reduction ratio, the
one the library publishes as its driven final drive; the front motor's order
is not analysed.
"""

from __future__ import annotations

from typing import Literal

from vibesensor.domain.vehicle_configuration import VehicleDrivetrain, VehicleFuelType

__all__ = [
    "Axle",
    "driven_axles",
    "final_drive_axle_for",
    "has_propshaft",
]

Axle = Literal["front", "rear"]


def driven_axles(drive_layout: VehicleDrivetrain | None) -> tuple[Axle, ...]:
    """The axles the layout drives; empty when the layout was not given."""

    if drive_layout == "FWD":
        return ("front",)
    if drive_layout == "RWD":
        return ("rear",)
    if drive_layout == "AWD":
        return ("front", "rear")
    return ()


def final_drive_axle_for(
    drive_layout: VehicleDrivetrain | None, final_drive_axle: Axle | None
) -> Axle | None:
    """The axle the final drive belongs to: the driven one for FWD/RWD.

    An AWD car keeps the axle it was given (the library's, when its row says);
    without a layout there is no axle.
    """

    if drive_layout == "FWD":
        return "front"
    if drive_layout == "RWD":
        return "rear"
    if drive_layout == "AWD":
        return final_drive_axle
    return None


def has_propshaft(
    drive_layout: VehicleDrivetrain | None,
    fuel_type: VehicleFuelType | None,
    final_drive_axle: Axle | None,
) -> bool | None:
    """Whether a propshaft carries drive to the rear axle; ``None`` when unknown."""

    if drive_layout is None:
        return None
    if drive_layout == "FWD" or fuel_type == "EV":
        return False
    # An AWD hybrid whose final drive is on the front axle is e-AWD: the
    # engine drives the front wheels and an electric motor the rear ones.
    return not (drive_layout == "AWD" and fuel_type == "PHEV" and final_drive_axle == "front")
