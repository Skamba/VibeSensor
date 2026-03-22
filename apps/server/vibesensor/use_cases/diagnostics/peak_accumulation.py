"""Raw peak-bin accumulation helpers for diagnostics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from math import floor as _math_floor

from vibesensor.domain import speed_bin_label

from ._types import AnalysisSampleInput, PhaseLabels, ensure_analysis_sample
from .helpers import _estimate_strength_floor_amp_g, _location_label, _sample_top_peaks
from .speed_profile_helpers import _phase_to_str


def _make_nested_int_defaultdict() -> defaultdict:
    """Create a nested defaultdict(int)."""
    return defaultdict(int)


class PeakBinStats:
    """Accumulated per-frequency-bin statistics collected from samples."""

    __slots__ = (
        "bin_amps",
        "bin_floors",
        "bin_location_counts",
        "bin_phase_counts",
        "bin_speed_amp_pairs",
        "bin_speed_bin_counts",
        "bin_speeds",
        "n_samples",
        "total_location_sample_counts",
        "total_locations",
        "total_speed_bin_counts",
    )

    def __init__(self) -> None:
        self.bin_amps: dict[float, list[float]] = defaultdict(list)
        self.bin_floors: dict[float, list[float]] = defaultdict(list)
        self.bin_speeds: dict[float, list[float]] = defaultdict(list)
        self.bin_speed_amp_pairs: dict[float, list[tuple[float, float]]] = defaultdict(list)
        dd_factory = _make_nested_int_defaultdict
        self.bin_location_counts: dict[float, dict[str, int]] = defaultdict(dd_factory)
        self.bin_speed_bin_counts: dict[float, dict[str, int]] = defaultdict(dd_factory)
        self.bin_phase_counts: dict[float, dict[str, int]] = defaultdict(dd_factory)
        self.total_speed_bin_counts: dict[str, int] = defaultdict(int)
        self.total_locations: set[str] = set()
        self.total_location_sample_counts: dict[str, int] = defaultdict(int)
        self.n_samples: int = 0


def accumulate_peak_bin_stats(
    samples: Sequence[AnalysisSampleInput],
    *,
    freq_bin_hz: float,
    freq_bin_hz_half: float,
    lang: str,
    per_sample_phases: PhaseLabels | None,
    has_phases: bool,
) -> PeakBinStats:
    """Accumulate per-sample data into frequency-bin statistics."""
    stats = PeakBinStats()

    local_speed_bin = speed_bin_label
    local_location = _location_label
    local_top_peaks = _sample_top_peaks
    local_floor_est = _estimate_strength_floor_amp_g
    local_phase_str = _phase_to_str
    floor_fn = _math_floor

    for i, raw_sample in enumerate(samples):
        sample = ensure_analysis_sample(raw_sample)
        stats.n_samples += 1
        speed = sample.speed_kmh
        sample_speed_bin = local_speed_bin(speed) if speed is not None and speed > 0 else None
        if sample_speed_bin is not None:
            stats.total_speed_bin_counts[sample_speed_bin] += 1
        floor_raw = local_floor_est(sample)
        floor_amp = floor_raw if floor_raw is not None else 0.0
        location = local_location(sample, lang=lang)
        if location:
            stats.total_locations.add(location)
            stats.total_location_sample_counts[location] += 1
        sample_phase: str | None = None
        if has_phases and per_sample_phases is not None and i < len(per_sample_phases):
            sample_phase = local_phase_str(per_sample_phases[i])
        for hz, amp in local_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            bin_center = floor_fn(hz / freq_bin_hz) * freq_bin_hz + freq_bin_hz_half
            stats.bin_amps[bin_center].append(amp)
            stats.bin_floors[bin_center].append(max(0.0, floor_amp))
            if speed is not None and speed > 0:
                stats.bin_speeds[bin_center].append(speed)
                stats.bin_speed_amp_pairs[bin_center].append((speed, amp))
            if location:
                stats.bin_location_counts[bin_center][location] += 1
            if sample_speed_bin is not None:
                stats.bin_speed_bin_counts[bin_center][sample_speed_bin] += 1
            if sample_phase is not None:
                stats.bin_phase_counts[bin_center][sample_phase] += 1

    return stats
