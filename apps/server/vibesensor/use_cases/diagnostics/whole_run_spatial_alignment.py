"""Deterministic whole-run multi-sensor window joins for spatial analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vibesensor.shared.types.raw_capture import RawCaptureCoverageState
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
)
from vibesensor.use_cases.diagnostics._sensor_locations import (
    client_locations_by_sensor,
    fallback_location_label,
)
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunWindowSpectralSummary,
    whole_run_spectral_summaries_by_sensor,
)
from vibesensor.vibration_strength import StrengthPeak

__all__ = [
    "AlignedSpatialSensorWindow",
    "AlignedSpatialWindow",
    "WholeRunSpatialAlignmentMatrix",
    "build_whole_run_spatial_alignment_matrix",
]


@dataclass(frozen=True, slots=True)
class AlignedSpatialSensorWindow:
    """One sensor's spectral summary aligned to a canonical whole-run window."""

    sensor_id: str
    location: str
    coverage_state: RawCaptureCoverageState
    returned_sample_start: int | None
    returned_sample_count: int
    dominant_freq_hz: float | None = None
    vibration_strength_db: float | None = None
    top_peaks: tuple[StrengthPeak, ...] = ()


@dataclass(frozen=True, slots=True)
class AlignedSpatialWindow:
    """All sensor rows aligned to one canonical whole-run context window."""

    window_index: int
    label: WholeRunContextWindowLabel
    sensor_windows: tuple[AlignedSpatialSensorWindow, ...]
    full_sensor_count: int
    partial_sensor_count: int
    empty_sensor_count: int
    missing_sensor_count: int


@dataclass(frozen=True, slots=True)
class WholeRunSpatialAlignmentMatrix:
    """Deterministic multi-sensor join surface for later coherence/hotspot scoring."""

    sensor_ids: tuple[str, ...]
    windows: tuple[AlignedSpatialWindow, ...]


def build_whole_run_spatial_alignment_matrix(
    *,
    spectral_manifest: WholeRunArtifactManifest,
    spectral_artifact_contents: Mapping[str, bytes],
    context_labels: Sequence[WholeRunContextWindowLabel],
    samples: Sequence[Sample],
    lang: str = "en",
) -> WholeRunSpatialAlignmentMatrix:
    """Join spectral summaries and context labels onto one deterministic window grid."""

    ordered_labels = _ordered_context_labels(
        context_labels=context_labels,
        expected_window_count=spectral_manifest.total_window_count,
    )
    summaries_by_sensor = whole_run_spectral_summaries_by_sensor(
        manifest=spectral_manifest,
        artifact_contents=spectral_artifact_contents,
    )
    client_locations = client_locations_by_sensor(samples, lang=lang)
    sensor_ids = tuple(sorted(set(summaries_by_sensor) | set(client_locations)))
    if not sensor_ids:
        raise ValueError("whole-run spatial alignment requires at least one sensor")
    windows = tuple(
        _aligned_window(
            label=label,
            sensor_ids=sensor_ids,
            summaries_by_sensor=summaries_by_sensor,
            client_locations=client_locations,
        )
        for label in ordered_labels
    )
    return WholeRunSpatialAlignmentMatrix(sensor_ids=sensor_ids, windows=windows)


def _ordered_context_labels(
    *,
    context_labels: Sequence[WholeRunContextWindowLabel],
    expected_window_count: int,
) -> tuple[WholeRunContextWindowLabel, ...]:
    ordered_labels = tuple(sorted(context_labels, key=lambda label: label.window_index))
    if len(ordered_labels) != expected_window_count:
        raise ValueError("whole-run spatial alignment requires one context label per window")
    if any(label.window_index != index for index, label in enumerate(ordered_labels)):
        raise ValueError("whole-run spatial alignment requires contiguous ordered context labels")
    return ordered_labels


def _aligned_window(
    *,
    label: WholeRunContextWindowLabel,
    sensor_ids: Sequence[str],
    summaries_by_sensor: Mapping[str, Sequence[WholeRunWindowSpectralSummary]],
    client_locations: Mapping[str, str],
) -> AlignedSpatialWindow:
    sensor_windows: list[AlignedSpatialSensorWindow] = []
    full_sensor_count = 0
    partial_sensor_count = 0
    empty_sensor_count = 0
    missing_sensor_count = 0
    for sensor_id in sensor_ids:
        summaries = summaries_by_sensor.get(sensor_id)
        if summaries is None:
            sensor_window = AlignedSpatialSensorWindow(
                sensor_id=sensor_id,
                location=client_locations.get(sensor_id, fallback_location_label(sensor_id)),
                coverage_state="missing",
                returned_sample_start=None,
                returned_sample_count=0,
            )
        else:
            summary = summaries[label.window_index]
            sensor_window = AlignedSpatialSensorWindow(
                sensor_id=sensor_id,
                location=client_locations.get(sensor_id, fallback_location_label(sensor_id)),
                coverage_state=summary.coverage_state,
                returned_sample_start=summary.returned_sample_start,
                returned_sample_count=summary.returned_sample_count,
                dominant_freq_hz=summary.dominant_freq_hz,
                vibration_strength_db=summary.vibration_strength_db,
                top_peaks=summary.top_peaks,
            )
        if sensor_window.coverage_state == "full":
            full_sensor_count += 1
        elif sensor_window.coverage_state == "partial":
            partial_sensor_count += 1
        elif sensor_window.coverage_state == "empty":
            empty_sensor_count += 1
        else:
            missing_sensor_count += 1
        sensor_windows.append(sensor_window)
    return AlignedSpatialWindow(
        window_index=label.window_index,
        label=label,
        sensor_windows=tuple(sensor_windows),
        full_sensor_count=full_sensor_count,
        partial_sensor_count=partial_sensor_count,
        empty_sensor_count=empty_sensor_count,
        missing_sensor_count=missing_sensor_count,
    )
