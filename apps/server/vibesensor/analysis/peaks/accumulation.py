"""Raw peak-bin accumulation helpers for diagnostics."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from vibesensor.analysis._types import PhaseLabels
from vibesensor.analysis.drive_table import DriveTable, counts_by_group, groups_in_order
from vibesensor.analysis.speed_profile_helpers import _phase_to_str
from vibesensor.recording.sample_columns import coded


class PeakBinStats:
    """Accumulated per-frequency-bin statistics collected from samples.

    The bins come in the order the drive's peaks first fall in them, each
    bin's values in the order of its peaks.
    """

    __slots__ = (
        "bin_amps",
        "bin_floors",
        "bin_location_counts",
        "bin_phase_counts",
        "bin_speed_amp_pairs",
        "bin_speed_bin_counts",
        "n_samples",
        "total_location_sample_counts",
        "total_locations",
        "total_speed_bin_counts",
    )

    def __init__(self) -> None:
        self.bin_amps: dict[float, list[float]] = {}
        self.bin_floors: dict[float, list[float]] = {}
        self.bin_speed_amp_pairs: dict[float, list[tuple[float, float]]] = {}
        self.bin_location_counts: dict[float, dict[str, int]] = {}
        self.bin_speed_bin_counts: dict[float, dict[str, int]] = {}
        self.bin_phase_counts: dict[float, dict[str, int]] = {}
        self.total_speed_bin_counts: dict[str, int] = {}
        self.total_locations: set[str] = set()
        self.total_location_sample_counts: dict[str, int] = {}
        self.n_samples: int = 0


def accumulate_peak_bin_stats(
    table: DriveTable,
    *,
    freq_bin_hz: float,
    freq_bin_hz_half: float,
    per_sample_phases: PhaseLabels | None,
    has_phases: bool,
) -> PeakBinStats:
    """Accumulate the drive's analysed peaks into frequency-bin statistics.

    Each peak counts in its bin with its sample's floor (0 where it has none),
    its speed and speed bin where the sample is moving, its sensor's label and
    its sample's phase label.
    """
    stats = PeakBinStats()
    stats.n_samples = table.size
    moving = table.moving
    stats.total_speed_bin_counts = table.speed_bin_counts()
    located = table.located
    location_counts = np.bincount(table.location_of, minlength=len(table.locations)).tolist()
    for location, count, is_located in zip(
        table.locations, location_counts, located.tolist(), strict=True
    ):
        if is_located and count:
            stats.total_locations.add(location)
            stats.total_location_sample_counts[location] = count
    phase_of, phases = _phase_codes(table, per_sample_phases, has_phases)

    row = table.peak_row
    centre = np.floor(table.peak_hz / freq_bin_hz) * freq_bin_hz + freq_bin_hz_half
    bins, bin_of = groups_in_order(centre)
    # The peaks bin by bin, each bin's in the drive's order.
    order = np.argsort(bin_of, kind="stable")
    bounds = np.searchsorted(bin_of[order], np.arange(len(bins) + 1)).tolist()
    ordered_row = row[order]
    amps = table.peak_amp[order].tolist()
    floors = table.floor_or_zero[ordered_row].tolist()
    peak_moving = moving[ordered_row]
    moving_bounds = np.concatenate(([0], np.cumsum(peak_moving)))[bounds].tolist()
    speed_amp_pairs = list(
        zip(
            table.speed_kmh[ordered_row][peak_moving].tolist(),
            table.peak_amp[order][peak_moving].tolist(),
            strict=True,
        )
    )
    ordered_bin = bin_of[order]
    location_counts_by_bin = counts_by_group(
        ordered_bin,
        table.location_of[ordered_row],
        located[table.location_of[ordered_row]],
        table.locations,
    )
    speed_bin_of = table.speed_bin_of[ordered_row]
    speed_bin_counts_by_bin = counts_by_group(
        ordered_bin, speed_bin_of, speed_bin_of >= 0, table.speed_bins
    )
    phase_counts_by_bin = (
        counts_by_group(ordered_bin, phase_of[ordered_row], phase_of[ordered_row] >= 0, phases)
        if phases
        else {}
    )
    for number, centre_hz in enumerate(bins):
        start, end = bounds[number], bounds[number + 1]
        stats.bin_amps[centre_hz] = amps[start:end]
        stats.bin_floors[centre_hz] = floors[start:end]
        moving_start, moving_end = moving_bounds[number], moving_bounds[number + 1]
        if moving_end > moving_start:
            stats.bin_speed_amp_pairs[centre_hz] = speed_amp_pairs[moving_start:moving_end]
        for counts, by_bin in (
            (stats.bin_location_counts, location_counts_by_bin),
            (stats.bin_speed_bin_counts, speed_bin_counts_by_bin),
            (stats.bin_phase_counts, phase_counts_by_bin),
        ):
            if number in by_bin:
                counts[centre_hz] = by_bin[number]
    return stats


def _phase_codes(
    table: DriveTable, per_sample_phases: PhaseLabels | None, has_phases: bool
) -> tuple[npt.NDArray[np.intp], list[str]]:
    """Each sample's phase label (``_phase_to_str``) as an index into the labels; -1 for none."""
    if not has_phases or per_sample_phases is None:
        return np.full(table.size, -1, dtype=np.intp), []
    labels = [_phase_to_str(phase) for phase in per_sample_phases[: table.size]]
    labels += [None] * (table.size - len(labels))
    codes, names = coded(labels)
    # A sample without a label is not counted.
    none_at = names.index(None) if None in names else -1
    if none_at >= 0:
        codes = np.where(codes == none_at, -1, codes)
    return codes, [name if name is not None else "" for name in names]
