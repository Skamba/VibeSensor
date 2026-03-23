"""Sensor/location helpers for diagnostics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from vibesensor.shared.locations import label_for_code as _label_for_code

from ._types import AnalysisSampleInput, ensure_analysis_sample


def _location_label(sample: AnalysisSampleInput, *, lang: str = "en") -> str:
    """Return a stable language-neutral location label for the sample."""
    del lang
    typed_sample = ensure_analysis_sample(sample)
    location_code = typed_sample.location.strip()
    if location_code:
        translated = _label_for_code(location_code)
        return str(translated) if translated else location_code

    client_name_raw = typed_sample.client_name.strip()
    if client_name_raw:
        return client_name_raw
    client_id_raw = typed_sample.client_id.strip()
    if client_id_raw:
        return f"Sensor …{client_id_raw[-4:]}"
    return "Unknown sensor"


def _locations_connected_throughout_run(
    samples: Sequence[AnalysisSampleInput],
    *,
    lang: str = "en",
) -> set[str]:
    by_location_times: dict[str, set[float]] = defaultdict(set)
    all_times: list[float] = []

    for raw_sample in samples:
        sample = ensure_analysis_sample(raw_sample)
        location = _location_label(sample, lang=lang)
        if not location:
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
