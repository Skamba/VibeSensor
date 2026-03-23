"""Shared exact analysis/history view shapes used by boundary and HTTP layers.

These TypedDicts are the single semantic owner for stable analysis/history
concepts that must be understood by both persistence-boundary payloads and
the HTTP/OpenAPI response schema. ``typing_extensions.TypedDict`` keeps these
shapes compatible with Pydantic schema generation on Python 3.11.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict
from typing_extensions import Required, TypedDict  # noqa: UP035 (Pydantic on Python 3.11)

__all__ = [
    "AmpVsPhaseRow",
    "FindingEvidenceMetrics",
    "FreqVsSpeedByFindingSeries",
    "LocationHotspotPayload",
    "MatchedAmpVsSpeedSeries",
    "MatchedPoint",
    "PeakTableRow",
    "PhaseBoundary",
    "PhaseEvidence",
    "PhaseSegmentOut",
    "PhaseSpeedBreakdownRow",
    "PlotDataResult",
    "SpectrogramResult",
    "SpeedBreakdownRow",
]

_IGNORE_EXTRA_TYPEDDICT_CONFIG = ConfigDict(extra="ignore")


class PeakTableRow(TypedDict):
    """Typed HTTP contract for one ranked peak table row."""

    rank: int
    frequency_hz: float
    order_label: str
    max_intensity_db: float | None
    median_intensity_db: float | None
    p95_intensity_db: float | None
    run_noise_baseline_db: float | None
    median_vs_run_noise_ratio: float
    p95_vs_run_noise_ratio: float
    strength_floor_db: float | None
    strength_db: float | None
    presence_ratio: float
    burstiness: float
    persistence_score: float
    suspected_source: str
    peak_classification: str
    typical_speed_band: str


class MatchedPoint(TypedDict, total=False):
    """HTTP contract for one serialized finding matched-point observation."""

    t_s: float | None
    speed_kmh: float | None
    predicted_hz: float | None
    matched_hz: float | None
    rel_error: float | None
    amp: float | None
    location: str | None
    phase: str | None


class PhaseEvidence(TypedDict, total=False):
    """HTTP contract for optional driving-phase evidence attached to a finding."""

    cruise_fraction: float | None
    phases_detected: list[str]


class LocationHotspotPayload(TypedDict, total=False):
    """HTTP contract for serialized location-hotspot evidence."""

    dominance_ratio: float | None
    location_count: int | None
    top_location: str | None
    second_location: str | None
    ambiguous_location: bool | None
    ambiguous_locations: list[str]
    localization_confidence: float | None
    weak_spatial_separation: bool | None


class FindingEvidenceMetrics(TypedDict, total=False):
    """HTTP contract for serialized evidence metrics attached to a finding."""

    match_rate: float | None
    global_match_rate: float | None
    focused_speed_band: str | None
    mean_relative_error: float | None
    mean_noise_floor_db: float | None
    vibration_strength_db: float | None
    possible_samples: int | None
    matched_samples: int | None
    frequency_correlation: float | None
    per_phase_confidence: dict[str, float] | None
    phases_with_evidence: int | None
    presence_ratio: float | None
    median_intensity_db: float | None
    p95_intensity_db: float | None
    max_intensity_db: float | None
    burstiness: float | None
    run_noise_baseline_db: float | None
    median_relative_to_run_noise: float | None
    p95_relative_to_run_noise: float | None
    sample_count: int | None
    total_samples: int | None
    spatial_concentration: float | None
    spatial_uniformity: float | None
    speed_uniformity: float | None


class SpeedBreakdownRow(TypedDict):
    """Typed HTTP contract for one speed-band aggregate row."""

    speed_range: str
    count: int
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


class PhaseSpeedBreakdownRow(TypedDict):
    """Typed HTTP contract for one phase-aware speed aggregate row."""

    phase: str
    count: int
    mean_speed_kmh: float | None
    max_speed_kmh: float | None
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


class SpectrogramResult(TypedDict, total=False):
    """Typed HTTP contract for a serialized spectrogram grid."""

    x_axis: Required[str]
    x_label_key: Required[str]
    x_bins: Required[list[float]]
    y_bins: Required[list[float]]
    cells: Required[list[list[float]]]
    max_amp: Required[float]
    x_bin_width: float | None
    y_bin_width: float | None


class MatchedAmpVsSpeedSeries(TypedDict):
    """Typed HTTP contract for one finding's amp-vs-speed series."""

    label: str
    points: list[tuple[float, float]]


class FreqVsSpeedByFindingSeries(TypedDict):
    """Typed HTTP contract for one finding's freq-vs-speed series."""

    label: str
    matched: list[tuple[float, float]]
    predicted: list[tuple[float, float]]


class AmpVsPhaseRow(TypedDict):
    """Typed HTTP contract for one phase-grouped vibration aggregate row."""

    phase: str
    count: int
    mean_vib_db: float
    max_vib_db: float | None
    mean_speed_kmh: float | None


class PhaseSegmentOut(TypedDict):
    """Typed HTTP contract for a serialized driving-phase segment."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None


class PhaseBoundary(TypedDict):
    """Typed HTTP contract for a phase-boundary marker."""

    phase: str
    t_s: float | None
    end_t_s: float | None


class PlotDataResult(TypedDict):
    """Typed HTTP contract for serialized plot data attached to a run summary."""

    vib_magnitude: list[tuple[float, float, str]]
    dominant_freq: list[tuple[float, float]]
    amp_vs_speed: list[tuple[float, float]]
    amp_vs_phase: list[AmpVsPhaseRow]
    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeries]
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries]
    steady_speed_distribution: dict[str, float] | None
    fft_spectrum: list[tuple[float, float]]
    fft_spectrum_raw: list[tuple[float, float]]
    peaks_spectrogram: SpectrogramResult
    peaks_spectrogram_raw: SpectrogramResult
    peaks_table: list[PeakTableRow]
    phase_segments: list[PhaseSegmentOut]
    phase_boundaries: list[PhaseBoundary]


def _configure_pydantic_schema(typed_dict: Any, config: ConfigDict) -> None:
    typed_dict.__pydantic_config__ = config


_configure_pydantic_schema(PeakTableRow, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(MatchedPoint, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(PhaseEvidence, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(LocationHotspotPayload, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(FindingEvidenceMetrics, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(SpectrogramResult, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(PlotDataResult, _IGNORE_EXTRA_TYPEDDICT_CONFIG)

_configure_pydantic_schema(SpeedBreakdownRow, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(PhaseSpeedBreakdownRow, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(MatchedAmpVsSpeedSeries, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(FreqVsSpeedByFindingSeries, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(AmpVsPhaseRow, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(PhaseSegmentOut, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
_configure_pydantic_schema(PhaseBoundary, _IGNORE_EXTRA_TYPEDDICT_CONFIG)
