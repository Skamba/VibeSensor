"""Sensor/location helpers for diagnostics."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import numpy.typing as npt

from vibesensor.domain.locations import label_for_code as _label_for_code
from vibesensor.recording.run_schema import RunMetadata, RunSensorMetadata
from vibesensor.recording.sample_columns import SampleColumns, coded, first_seen, rows_of_groups


def _sensor_snapshot_label(snapshot: RunSensorMetadata, *, lang: str = "en") -> str:
    del lang
    location_code = snapshot.location_code.strip()
    if location_code:
        translated = _label_for_code(location_code)
        return str(translated) if translated else location_code
    display_name = snapshot.display_name.strip()
    if display_name:
        return display_name
    sensor_id = snapshot.sensor_id.strip()
    if sensor_id:
        return fallback_location_label(sensor_id)
    return "Unknown sensor"


def location_labels(
    samples: SampleColumns,
    metadata: RunMetadata | None = None,
) -> tuple[npt.NDArray[np.intp], list[str]]:
    """Each sample's stable language-neutral location label, as an index into the labels.

    A sensor in *metadata*'s sensor snapshot has the label of its snapshot,
    another the label of its samples' own location code, name and client id.
    The labels come in the order a pass over the samples meets them in.
    """
    by_sensor: list[str] = []
    for location, client_name, client_id in samples.sensors:
        snapshot = metadata.sensor_snapshot_for(client_id) if metadata is not None else None
        by_sensor.append(
            _sensor_snapshot_label(snapshot)
            if snapshot is not None
            else _sample_location_label(location, client_name, client_id)
        )
    label_of_sensor, labels = coded(by_sensor)
    return first_seen(label_of_sensor[samples.sensor_of], labels)


# A drive's samples come from a few sensors, and each step of the analysis asks
# for every sample's label.
@lru_cache(maxsize=256)
def _sample_location_label(location: str, client_name: str, client_id: str) -> str:
    """The label of a sample with location code *location* from sensor *client_name*."""
    location_code = location.strip()
    if location_code:
        translated = _label_for_code(location_code)
        return str(translated) if translated else location_code

    client_name_raw = client_name.strip()
    if client_name_raw:
        return client_name_raw
    client_id_raw = client_id.strip()
    if client_id_raw:
        return fallback_location_label(client_id_raw)
    return "Unknown sensor"


def fallback_location_label(client_id: str) -> str:
    """Return a stable fallback label when no explicit location is available."""

    suffix = client_id[-4:] if len(client_id) >= 4 else client_id
    return f"Sensor …{suffix}" if suffix else "Unknown sensor"


def _locations_connected_throughout_run(
    samples: SampleColumns,
    *,
    metadata: RunMetadata | None = None,
) -> set[str]:
    """Return locations that remain present across the full run span."""
    label_of, labels = location_labels(samples, metadata)
    usable = ~np.isnan(samples.vibration_strength_db) & ~np.isnan(samples.t_s)
    by_location_times: dict[str, set[float]] = {}
    all_times: list[float] = []
    for location, rows in zip(
        labels, rows_of_groups(np.where(usable, label_of, -1), len(labels)), strict=True
    ):
        if location and rows.size:
            times = samples.t_s[rows].tolist()
            by_location_times[location] = set(times)
            all_times.extend(times)

    if not by_location_times:
        return set()
    if not all_times:
        return set(by_location_times.keys())

    run_start = min(all_times)
    run_end = max(all_times)
    run_duration = max(0.0, run_end - run_start)
    edge_tolerance_s = max(0.75, min(3.0, run_duration * 0.08))

    max_count = max((len(times) for times in by_location_times.values()), default=0)
    min_required_count = int(max_count * 0.80) if max_count >= 5 else 1

    connected: set[str] = set()
    for location, times in by_location_times.items():
        if not times:
            continue
        if len(times) < min_required_count:
            continue
        sorted_times = sorted(times)
        loc_start = sorted_times[0]
        loc_end = sorted_times[-1]
        if loc_start <= (run_start + edge_tolerance_s) and loc_end >= (run_end - edge_tolerance_s):
            max_internal_gap = max(
                (curr - prev for prev, curr in zip(sorted_times, sorted_times[1:], strict=False)),
                default=0.0,
            )
            if max_internal_gap <= (edge_tolerance_s * 2.0):
                connected.add(location)

    return connected
