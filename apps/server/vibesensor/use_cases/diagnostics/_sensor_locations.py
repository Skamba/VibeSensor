"""Sensor/location helpers for diagnostics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from vibesensor.shared.locations import label_for_code as _label_for_code
from vibesensor.shared.types.run_schema import RunMetadata, RunSensorMetadata

from ._sample_metrics import _primary_vibration_strength_db
from ._types import Sample


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


def _location_label(
    sample: Sample,
    *,
    metadata: RunMetadata | None = None,
    lang: str = "en",
) -> str:
    """Return a stable language-neutral location label for the sample."""
    if metadata is not None:
        snapshot = metadata.sensor_snapshot_for(sample.client_id)
        if snapshot is not None:
            return _sensor_snapshot_label(snapshot, lang=lang)
    del lang
    location_code = sample.location.strip()
    if location_code:
        translated = _label_for_code(location_code)
        return str(translated) if translated else location_code

    client_name_raw = sample.client_name.strip()
    if client_name_raw:
        return client_name_raw
    client_id_raw = sample.client_id.strip()
    if client_id_raw:
        return fallback_location_label(client_id_raw)
    return "Unknown sensor"


def client_locations_by_sensor(
    samples: Sequence[Sample],
    *,
    metadata: RunMetadata | None = None,
    lang: str = "en",
) -> dict[str, str]:
    """Return deterministic location labels keyed by client id."""

    locations: dict[str, str] = {}
    for sample in samples:
        client_id = sample.client_id.strip()
        if not client_id or client_id in locations:
            continue
        locations[client_id] = _location_label(sample, metadata=metadata, lang=lang)
    return locations


def fallback_location_label(client_id: str) -> str:
    """Return a stable fallback label when no explicit location is available."""

    suffix = client_id[-4:] if len(client_id) >= 4 else client_id
    return f"Sensor …{suffix}" if suffix else "Unknown sensor"


def _locations_connected_throughout_run(
    samples: Sequence[Sample],
    *,
    metadata: RunMetadata | None = None,
    lang: str = "en",
) -> set[str]:
    """Return locations that remain present across the full run span."""
    by_location_times: dict[str, set[float]] = defaultdict(set)
    all_times: list[float] = []

    for sample in samples:
        location = _location_label(sample, metadata=metadata, lang=lang)
        if not location:
            continue
        if _primary_vibration_strength_db(sample) is None:
            continue
        t_s = sample.t_s
        if t_s is None:
            continue
        by_location_times[location].add(t_s)
        all_times.append(t_s)

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
