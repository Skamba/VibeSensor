"""Sensor mount-orientation helpers for vehicle-axis analysis."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Literal

import numpy as np
import numpy.typing as npt

from vibesensor.shared.fft_analysis import AXES, Axis

type AxisFrame = Literal["sensor_local", "vehicle"]
type SignedAxis = Literal["+x", "-x", "+y", "-y", "+z", "-z"]

_AXIS_INDEX: dict[Axis, int] = {"x": 0, "y": 1, "z": 2}
_SIGNED_AXIS_ALIASES: dict[str, SignedAxis] = {
    "x": "+x",
    "+x": "+x",
    "forward": "+x",
    "+forward": "+x",
    "front": "+x",
    "+front": "+x",
    "-x": "-x",
    "backward": "-x",
    "-forward": "-x",
    "rear": "-x",
    "+rear": "-x",
    "left": "+y",
    "+left": "+y",
    "y": "+y",
    "+y": "+y",
    "right": "-y",
    "+right": "-y",
    "-left": "-y",
    "-y": "-y",
    "up": "+z",
    "+up": "+z",
    "z": "+z",
    "+z": "+z",
    "down": "-z",
    "+down": "-z",
    "-up": "-z",
    "-z": "-z",
}
_IDENTITY_LABELS = frozenset(
    {
        "aligned",
        "identity",
        "vehicle",
        "vehicle_aligned",
        "vehicle-aligned",
        "vehicle axes",
        "vehicle_axes",
    }
)
_UNKNOWN_LABELS = frozenset({"", "unknown", "unset", "unspecified", "n/a", "na", "none"})


@dataclass(frozen=True, slots=True)
class AxisOrientation:
    """Mapping from sensor-local axes into vehicle x/y/z axes."""

    vehicle_axes_from_sensor: tuple[SignedAxis, SignedAxis, SignedAxis]


def parse_mount_orientation(value: str | None) -> AxisOrientation | None:
    """Parse a mount-orientation string into a vehicle-axis mapping.

    Supported explicit mappings use three signed axes, where each token names the sensor-local axis
    that supplies vehicle x, vehicle y, then vehicle z. For example, ``+y,-x,+z`` means vehicle x
    comes from sensor +y, vehicle y from sensor -x, and vehicle z from sensor +z.
    """

    normalized = _normalize_orientation(value)
    if normalized in _UNKNOWN_LABELS:
        return None
    if normalized in _IDENTITY_LABELS:
        return AxisOrientation(("+x", "+y", "+z"))

    tokens = _mapping_tokens(normalized)
    if tokens is None:
        return None
    signed_axes: list[SignedAxis] = []
    for token in tokens:
        signed_axis = _SIGNED_AXIS_ALIASES.get(token)
        if signed_axis is None:
            return None
        signed_axes.append(signed_axis)
    if {axis[-1] for axis in signed_axes} != {"x", "y", "z"}:
        return None
    return AxisOrientation((signed_axes[0], signed_axes[1], signed_axes[2]))


def transform_axis_matrix_to_vehicle(
    axis_samples: npt.NDArray[np.float32],
    orientation: AxisOrientation,
) -> npt.NDArray[np.float32]:
    """Return samples reordered/sign-flipped into vehicle x/y/z axes."""

    transformed = np.empty_like(axis_samples, dtype=np.float32)
    for vehicle_index, signed_axis in enumerate(orientation.vehicle_axes_from_sensor):
        sign = -1.0 if signed_axis.startswith("-") else 1.0
        source_axis = _axis_from_signed_axis(signed_axis)
        transformed[vehicle_index] = axis_samples[_AXIS_INDEX[source_axis]] * np.float32(sign)
    return transformed


def estimate_gravity_axis(axis_samples_g: npt.NDArray[np.float32]) -> SignedAxis | None:
    """Estimate the dominant static-gravity axis from window mean acceleration."""

    if axis_samples_g.ndim != 2 or axis_samples_g.shape[0] != len(AXES):
        return None
    means = np.mean(axis_samples_g.astype(np.float32, copy=False), axis=1)
    if not np.all(np.isfinite(means)):
        return None
    norm = sqrt(float(np.sum(means * means)))
    if not isfinite(norm) or norm < 0.25:
        return None
    axis_index = int(np.argmax(np.abs(means)))
    axis = AXES[axis_index]
    if axis == "x":
        return "+x" if float(means[axis_index]) >= 0.0 else "-x"
    if axis == "y":
        return "+y" if float(means[axis_index]) >= 0.0 else "-y"
    return "+z" if float(means[axis_index]) >= 0.0 else "-z"


def _axis_from_signed_axis(value: SignedAxis) -> Axis:
    if value.endswith("x"):
        return "x"
    if value.endswith("y"):
        return "y"
    return "z"


def _normalize_orientation(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().replace(";", ",").split())


def _mapping_tokens(value: str) -> tuple[str, str, str] | None:
    if ":" in value:
        _, value = value.rsplit(":", maxsplit=1)
    compact = value.replace(" ", "")
    tokens = tuple(token for token in compact.split(",") if token)
    if len(tokens) != 3:
        return None
    return tokens
