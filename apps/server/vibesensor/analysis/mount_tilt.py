"""Loose-mount check: a sensor whose gravity reading turns on its own.

A firmly fixed sensor turns only with the part it sits on, and so with the
car: grade, braking, cornering and steering turn every sensor's reading of
gravity and the car's acceleration about alike. A sensor turned on its fixing
(sagged on a loose tie, slipped on a pad) reads the same car turned by an angle
of its own. Each raw window's mean is that reading (the 0 Hz part of the
signal); the check compares, between two stretches of the drive, how far each
sensor's reading turned with how far the other sensors' readings turned.

Only stretches of driving in which the car's own reading hardly turned are
compared, so the parts' own small movements (the body rolling and pitching on
its springs, a front wheel steering) stay well under the threshold. The basis
of every number is in docs/metrics.md ("Loose-mount check").
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from vibesensor.analysis._sensor_locations import _location_label
from vibesensor.analysis._types import Sample
from vibesensor.common.json_utils import i18n_ref
from vibesensor.domain.locations import location_code_for_label
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.summary.run_context_warning import (
    WARNING_CODE_SENSOR_LOOSE_MOUNT,
    RunContextWarning,
)

__all__ = ["LooseMount", "find_loose_mounts", "loose_mount_warnings"]

# Driving only: below this the front wheels may be steered far (parking), and a
# stationary car tells no drive apart.
_MIN_SPEED_KMH = 25.0
# Stretches of the drive compared with one another: 5 s, longer on a long
# drive so that at most 240 are compared pairwise.
_SEGMENT_S = 5.0
_MAX_SEGMENTS = 240
_MIN_WINDOWS_PER_SEGMENT = 2
# A window whose mean is far from the sensor's usual 1 g is not gravity (a
# clipped or broken window).
_MAX_MAGNITUDE_RATIO = 1.5
# Two stretches are compared when the other sensors' readings turned at most
# this far between them: the car's acceleration changed by under 0.18 g.
_MAX_COMMON_TURN_DEG = 10.0
# A sensor turned this much more than the others is not turning with the car.
_LOOSE_TURN_DEG = 8.0
_MIN_SENSORS = 3


@dataclass(frozen=True, slots=True)
class LooseMount:
    """A sensor whose reading turned more than the car did."""

    client_id: str
    location: str
    turn_deg: float


def find_loose_mounts(
    samples: Sequence[Sample],
    window_means: Sequence[tuple[float, float, float] | None],
    *,
    metadata: RunMetadata,
) -> tuple[LooseMount, ...]:
    """The sensors that turned on their fixing during the drive (needs three or more)."""
    if len(window_means) != len(samples):
        return ()
    rows: dict[str, list[tuple[float, tuple[float, float, float]]]] = defaultdict(list)
    labels: dict[str, str] = {}
    for sample, mean in zip(samples, window_means, strict=True):
        if mean is None or sample.t_s is None:
            continue
        if sample.speed_kmh is None or sample.speed_kmh < _MIN_SPEED_KMH:
            continue
        rows[sample.client_id].append((float(sample.t_s), mean))
        labels.setdefault(sample.client_id, _location_label(sample, metadata=metadata))
    if len(rows) < _MIN_SENSORS:
        return ()
    sensors = sorted(rows)
    start_s = min(t_s for sensor_rows in rows.values() for t_s, _ in sensor_rows)
    end_s = max(t_s for sensor_rows in rows.values() for t_s, _ in sensor_rows)
    segment_s = max(_SEGMENT_S, (end_s - start_s) / (_MAX_SEGMENTS - 1))
    segment_count = int((end_s - start_s) // segment_s) + 1
    # (sensor, segment, xyz): each stretch's mean direction, NaN where too few windows.
    directions = np.full((len(sensors), segment_count, 3), np.nan)
    for index, sensor in enumerate(sensors):
        times = np.array([t_s for t_s, _ in rows[sensor]])
        vectors = np.array([mean for _, mean in rows[sensor]], dtype=np.float64)
        norms = np.linalg.norm(vectors, axis=1)
        usual = float(np.median(norms))
        keep = (norms > usual / _MAX_MAGNITUDE_RATIO) & (norms < usual * _MAX_MAGNITUDE_RATIO)
        segments = ((times[keep] - start_s) // segment_s).astype(int)
        units = vectors[keep] / norms[keep, None]
        sums = np.zeros((segment_count, 3))
        np.add.at(sums, segments, units)
        counts = np.bincount(segments, minlength=segment_count)
        filled = counts >= _MIN_WINDOWS_PER_SEGMENT
        lengths = np.linalg.norm(sums[filled], axis=1, keepdims=True)
        directions[index, filled] = sums[filled] / lengths
    # (sensor, pair of segments): how far each sensor's reading turned between two stretches.
    first, second = np.triu_indices(segment_count, k=1)
    cosines = np.einsum("ips,ips->ip", directions[:, first], directions[:, second])
    turns = np.degrees(np.arccos(np.clip(cosines, -1.0, 1.0)))
    found: list[LooseMount] = []
    for index, sensor in enumerate(sensors):
        # The other sensors' median turn: how far the car's own reading turned.
        others = np.sort(np.delete(turns, index, axis=0), axis=0)  # NaN last
        count = np.sum(~np.isnan(others), axis=0)
        middle = np.stack(((count - 1) // 2, count // 2))
        common = np.take_along_axis(others, middle, axis=0).mean(axis=0)
        compared = (
            (count >= _MIN_SENSORS - 1) & ~np.isnan(turns[index]) & (common <= _MAX_COMMON_TURN_DEG)
        )
        if not compared.any():
            continue
        excess = float(np.max(turns[index][compared] - common[compared]))
        if excess >= _LOOSE_TURN_DEG:
            found.append(LooseMount(sensor, labels[sensor], round(excess, 1)))
    return tuple(found)


def loose_mount_warnings(loose: Sequence[LooseMount]) -> list[RunContextWarning]:
    """One run-quality warning per loose sensor."""
    warnings: list[RunContextWarning] = []
    for mount in loose:
        code = location_code_for_label(mount.location)
        location = i18n_ref(f"LOC_{code.upper()}") if code else mount.location
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_SENSOR_LOOSE_MOUNT,
                severity="warn",
                applies_to="location_analysis",
                title=i18n_ref("RUN_CONTEXT_WARNING_SENSOR_LOOSE_MOUNT_TITLE", location=location),
                detail=i18n_ref(
                    "RUN_CONTEXT_WARNING_SENSOR_LOOSE_MOUNT_DETAIL",
                    degrees=f"{math.floor(mount.turn_deg):.0f}",
                ),
            )
        )
    return warnings
