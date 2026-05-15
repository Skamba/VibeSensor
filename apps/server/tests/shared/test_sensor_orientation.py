from __future__ import annotations

import numpy as np
import pytest

from vibesensor.shared.sensor_orientation import (
    estimate_gravity_axis,
    parse_mount_orientation,
    transform_axis_matrix_to_vehicle,
)


@pytest.mark.parametrize(
    ("raw", "vehicle_axes_from_sensor"),
    [
        ("vehicle-aligned", ("+x", "+y", "+z")),
        ("+y,-x,+z", ("+y", "-x", "+z")),
    ],
)
def test_parse_mount_orientation_accepts_aliases_and_axis_mappings(
    raw: str,
    vehicle_axes_from_sensor: tuple[str, str, str],
) -> None:
    orientation = parse_mount_orientation(raw)

    assert orientation is not None
    assert orientation.vehicle_axes_from_sensor == vehicle_axes_from_sensor


def test_parse_mount_orientation_rejects_unknown_or_duplicate_mapping() -> None:
    assert parse_mount_orientation(None) is None
    assert parse_mount_orientation("diagonal") is None
    assert parse_mount_orientation("+x,+x,+z") is None


def test_transform_axis_matrix_to_vehicle_reorders_and_flips_axes() -> None:
    orientation = parse_mount_orientation("+y,-x,+z")
    assert orientation is not None
    samples = np.array(
        [
            [1.0, 2.0, 3.0],
            [10.0, 20.0, 30.0],
            [100.0, 200.0, 300.0],
        ],
        dtype=np.float32,
    )

    transformed = transform_axis_matrix_to_vehicle(samples, orientation)

    assert np.array_equal(transformed[0], samples[1])
    assert np.array_equal(transformed[1], -samples[0])
    assert np.array_equal(transformed[2], samples[2])


def test_estimate_gravity_axis_uses_window_mean_acceleration() -> None:
    samples = np.array(
        [
            [0.02, -0.01, 0.0],
            [0.01, 0.02, -0.01],
            [-1.0, -0.98, -1.02],
        ],
        dtype=np.float32,
    )

    assert estimate_gravity_axis(samples) == "-z"
