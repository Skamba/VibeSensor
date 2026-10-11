"""A drive's samples as columns, and their analysed peaks as one flat table.

Built once per analysis (``build_drive_table``) and read by every stage that
walks the samples' peaks, floors, speeds and sensors: each reads arrays, so
none re-derives a sample's peaks, floor, speed bin or label one sample at a
time. The distinct values of a text column (a sensor's label, a speed bin,
an RPM source) are kept once, in the order they first come, with each
sample's index into them: the order a pass over the samples meets them in.
See "Drive table" in docs/analysis_pipeline.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from vibesensor.analysis._sample_metrics import _floor_from_peaks
from vibesensor.analysis._sensor_locations import _sample_location_label
from vibesensor.analysis._types import Sample
from vibesensor.analysis.constants import MIN_ANALYSIS_FREQ_HZ
from vibesensor.domain.finding import speed_bin_label
from vibesensor.dsp.window_spectrum import WindowSpectrum
from vibesensor.recording.sample_peaks import SamplePeaks

__all__ = [
    "DriveTable",
    "build_drive_table",
    "coded",
    "counts_by_group",
    "first_seen",
    "groups_in_order",
]

# The ranked peaks of a sample the analysis looks at.
_ANALYSED_PEAKS = 8


@dataclass(frozen=True, slots=True, eq=False)
class DriveTable:
    """A drive's samples as columns, with their analysed peaks (``build_drive_table``).

    A sample's sensor, label and speed bin are an index into the drive's own
    (``sensors``, ``locations``, ``speed_bins``), in the order they first come;
    a value a sample does not have is NaN in a float column, with a mask
    saying which samples have one.
    """

    # Each sample's sensor: its (location code, name, client id).
    sensor_of: npt.NDArray[np.intp]
    sensors: Sequence[tuple[str, str, str]]
    # Each sample's sensor label (``_location_label``) and client id.
    location_of: npt.NDArray[np.intp]
    locations: Sequence[str]
    client_of: npt.NDArray[np.intp]
    clients: Sequence[str]
    t_s: npt.NDArray[np.float64]
    timed: npt.NDArray[np.bool_]
    speed_kmh: npt.NDArray[np.float64]
    has_speed: npt.NDArray[np.bool_]
    # The speed bin (``speed_bin_label``) of each moving sample; -1 where it is not moving.
    speed_bin_of: npt.NDArray[np.intp]
    speed_bins: Sequence[str]
    # Each sample's floor: its own where over 0, else from its analysed peaks
    # (``_sample_metrics._floor_from_peaks``).
    floor_amp_g: npt.NDArray[np.float64]
    has_floor: npt.NDArray[np.bool_]
    engine_rpm: npt.NDArray[np.float64]
    has_engine_rpm: npt.NDArray[np.bool_]
    engine_rpm_source_of: npt.NDArray[np.intp]
    engine_rpm_sources: Sequence[str]
    gear: npt.NDArray[np.float64]
    has_gear: npt.NDArray[np.bool_]
    final_drive_ratio: npt.NDArray[np.float64]
    has_final_drive_ratio: npt.NDArray[np.bool_]
    spectra: Sequence[WindowSpectrum | None]
    # The analysed peaks (``_analysed_peaks``), sample by sample in rank
    # order: each one's sample, frequency, amplitude and local floor (NaN where
    # it has none), and where each sample's run of them starts (one more entry
    # than samples).
    peak_row: npt.NDArray[np.intp]
    peak_hz: npt.NDArray[np.float64]
    peak_amp: npt.NDArray[np.float64]
    peak_local_floor_amp_g: npt.NDArray[np.float64]
    peak_start: npt.NDArray[np.intp]

    @property
    def size(self) -> int:
        return int(self.t_s.size)

    @property
    def moving(self) -> npt.NDArray[np.bool_]:
        """The samples with a speed over 0."""
        return self.speed_bin_of >= 0

    @property
    def floor_or_zero(self) -> npt.NDArray[np.float64]:
        """Each sample's floor, 0 where it has none."""
        return np.where(self.has_floor, self.floor_amp_g, 0.0)

    @property
    def located(self) -> npt.NDArray[np.bool_]:
        """Which of ``locations`` name a place (not empty)."""
        return np.array([bool(location) for location in self.locations], dtype=np.bool_)

    def speed_bin_counts(self) -> dict[str, int]:
        """How many samples fall in each speed bin, in the bins' order."""
        counts = np.bincount(self.speed_bin_of[self.moving], minlength=len(self.speed_bins))
        return dict(zip(self.speed_bins, counts.tolist(), strict=True))

    def subset(self, rows: npt.NDArray[np.intp]) -> DriveTable:
        """The samples at *rows* (ascending) as a drive table of their own."""
        keep = np.zeros(self.size, dtype=np.bool_)
        keep[rows] = True
        renumbered = np.cumsum(keep) - 1
        peaks = keep[self.peak_row]
        peak_row = renumbered[self.peak_row[peaks]]
        sensor_of, sensors = first_seen(self.sensor_of[rows], self.sensors)
        location_of, locations = first_seen(self.location_of[rows], self.locations)
        client_of, clients = first_seen(self.client_of[rows], self.clients)
        speed_bin_of, speed_bins = first_seen(self.speed_bin_of[rows], self.speed_bins)
        source_of, sources = first_seen(self.engine_rpm_source_of[rows], self.engine_rpm_sources)
        return DriveTable(
            sensor_of=sensor_of,
            sensors=sensors,
            location_of=location_of,
            locations=locations,
            client_of=client_of,
            clients=clients,
            t_s=self.t_s[rows],
            timed=self.timed[rows],
            speed_kmh=self.speed_kmh[rows],
            has_speed=self.has_speed[rows],
            speed_bin_of=speed_bin_of,
            speed_bins=speed_bins,
            floor_amp_g=self.floor_amp_g[rows],
            has_floor=self.has_floor[rows],
            engine_rpm=self.engine_rpm[rows],
            has_engine_rpm=self.has_engine_rpm[rows],
            engine_rpm_source_of=source_of,
            engine_rpm_sources=sources,
            gear=self.gear[rows],
            has_gear=self.has_gear[rows],
            final_drive_ratio=self.final_drive_ratio[rows],
            has_final_drive_ratio=self.has_final_drive_ratio[rows],
            spectra=[self.spectra[row] for row in rows.tolist()],
            peak_row=peak_row,
            peak_hz=self.peak_hz[peaks],
            peak_amp=self.peak_amp[peaks],
            peak_local_floor_amp_g=self.peak_local_floor_amp_g[peaks],
            peak_start=_starts(peak_row, int(rows.size)),
        )


def first_seen[T](
    codes: npt.NDArray[np.intp], names: Sequence[T]
) -> tuple[npt.NDArray[np.intp], list[T]]:
    """*codes* (indexes into *names*; -1 for none) renumbered by the order they first come.

    The names come back in that order (those no code uses dropped): the order
    one pass over the codes meets them in. A code of -1 stays -1.
    """
    present = codes[codes >= 0]
    distinct, first = np.unique(present, return_index=True)
    ordered = distinct[np.argsort(first, kind="stable")]
    # One entry more than there are names, never numbered: where -1 lands.
    number = np.full(len(names) + 1, -1, dtype=np.intp)
    number[ordered] = np.arange(ordered.size)
    return number[codes], [names[code] for code in ordered.tolist()]


def groups_in_order(
    keys: npt.NDArray[np.float64],
) -> tuple[list[float], npt.NDArray[np.intp]]:
    """The distinct *keys* in the order they first come, and each entry's index into them."""
    distinct, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    ordered = np.argsort(first, kind="stable")
    number = np.empty(distinct.size, dtype=np.intp)
    number[ordered] = np.arange(distinct.size)
    return distinct[ordered].tolist(), number[inverse.reshape(-1)]


def counts_by_group[T](
    group_of: npt.NDArray[np.intp],
    code_of: npt.NDArray[np.intp],
    counted: npt.NDArray[np.bool_],
    names: Sequence[T],
) -> dict[int, dict[T, int]]:
    """Each group's count of each name among its *counted* entries, in the order they first come.

    *group_of* is sorted (the entries group by group); *code_of* indexes *names*.
    A group without counted entries is left out.
    """
    width = len(names) + 1
    pair = group_of[counted] * width + code_of[counted]
    pairs, first, counts = np.unique(pair, return_index=True, return_counts=True)
    ordered = np.argsort(first, kind="stable")
    by_group: dict[int, dict[T, int]] = {}
    for key, count in zip(pairs[ordered].tolist(), counts[ordered].tolist(), strict=True):
        number, code = divmod(key, width)
        by_group.setdefault(number, {})[names[code]] = count
    return by_group


def coded[T](values: Sequence[T]) -> tuple[npt.NDArray[np.intp], list[T]]:
    """Each of *values* as an index into the distinct values, which come in first-seen order."""
    names: dict[T, int] = {}
    codes = np.array([names.setdefault(value, len(names)) for value in values], dtype=np.intp)
    return codes, list(names)


def _floats(
    values: Sequence[float | None],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
    """*values* as floats (NaN where ``None``), and which are not ``None``."""
    known = np.array([value is not None for value in values], dtype=np.bool_)
    return (
        np.array([value if value is not None else np.nan for value in values], dtype=np.float64),
        known,
    )


def _starts(rows: npt.NDArray[np.intp], size: int) -> npt.NDArray[np.intp]:
    """Where each of *size* samples' run of entries starts in *rows* (sorted), and the end."""
    starts = np.zeros(size + 1, dtype=np.intp)
    np.cumsum(np.bincount(rows, minlength=size), out=starts[1:])
    return starts


def build_drive_table(samples: Sequence[Sample], peaks: SamplePeaks) -> DriveTable:
    """*samples*, whose peaks are *peaks*, as a ``DriveTable``."""
    size = len(samples)
    sensor_of, sensors = coded(
        [(sample.location, sample.client_name, sample.client_id) for sample in samples]
    )
    # The sensors come in the order they first come, so their labels and
    # clients do too.
    label_of, locations = coded([_sample_location_label(*sensor) for sensor in sensors])
    client_id_of, clients = coded([client_id for _location, _name, client_id in sensors])
    t_s, timed = _floats([sample.t_s for sample in samples])
    speed_kmh, has_speed = _floats([sample.speed_kmh for sample in samples])
    speed_bin_of, speed_bins = _speed_bins(speed_kmh, has_speed)
    engine_rpm, has_engine_rpm = _floats([sample.engine_rpm for sample in samples])
    engine_rpm_source_of, engine_rpm_sources = coded(
        [sample.engine_rpm_source for sample in samples]
    )
    gear, has_gear = _floats([sample.gear for sample in samples])
    final_drive_ratio, has_final_drive_ratio = _floats(
        [sample.final_drive_ratio for sample in samples]
    )
    analysed = _analysed_peaks(peaks)
    peak_row = peaks.row[analysed]
    peak_amp = peaks.amp[analysed]
    peak_start = _starts(peak_row, size)
    floor_amp_g, has_floor = _floors(
        [sample.strength_floor_amp_g for sample in samples], peak_amp, peak_start
    )
    return DriveTable(
        sensor_of=sensor_of,
        sensors=sensors,
        location_of=label_of[sensor_of],
        locations=locations,
        client_of=client_id_of[sensor_of],
        clients=clients,
        t_s=t_s,
        timed=timed,
        speed_kmh=speed_kmh,
        has_speed=has_speed,
        speed_bin_of=speed_bin_of,
        speed_bins=speed_bins,
        floor_amp_g=floor_amp_g,
        has_floor=has_floor,
        engine_rpm=engine_rpm,
        has_engine_rpm=has_engine_rpm,
        engine_rpm_source_of=engine_rpm_source_of,
        engine_rpm_sources=engine_rpm_sources,
        gear=gear,
        has_gear=has_gear,
        final_drive_ratio=final_drive_ratio,
        has_final_drive_ratio=has_final_drive_ratio,
        spectra=[sample.spectrum for sample in samples],
        peak_row=peak_row,
        peak_hz=peaks.hz[analysed],
        peak_amp=peak_amp,
        peak_local_floor_amp_g=peaks.local_floor_amp_g[analysed],
        peak_start=peak_start,
    )


def _speed_bins(
    speed_kmh: npt.NDArray[np.float64], has_speed: npt.NDArray[np.bool_]
) -> tuple[npt.NDArray[np.intp], list[str]]:
    """Each moving sample's speed bin (``speed_bin_label``), -1 where it is not moving."""
    moving = has_speed & (speed_kmh > 0)
    speeds, speed_of = np.unique(speed_kmh[moving], return_inverse=True)
    label_of, labels = coded([speed_bin_label(speed) for speed in speeds.tolist()])
    codes = np.full(speed_kmh.size, -1, dtype=np.intp)
    codes[moving] = label_of[speed_of]
    return first_seen(codes, labels)


def _analysed_peaks(peaks: SamplePeaks) -> npt.NDArray[np.bool_]:
    """Which peaks are analysed: a sample's first ranked ones, those above the analysis floor."""
    return (
        (peaks.rank() < _ANALYSED_PEAKS)
        & (peaks.hz > 0)
        & (peaks.amp > 0)
        & (peaks.hz >= MIN_ANALYSIS_FREQ_HZ)
    )


def _floors(
    strength_floors: Sequence[float | None],
    peak_amp: npt.NDArray[np.float64],
    peak_start: npt.NDArray[np.intp],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
    """Each sample's floor: its own where over 0, else from its peaks (``_floor_from_peaks``)."""
    floors, _known = _floats(strength_floors)
    has_floor = floors > 0
    floors[~has_floor] = np.nan
    for row in np.flatnonzero(~has_floor).tolist():
        estimate = _floor_from_peaks(peak_amp[peak_start[row] : peak_start[row + 1]].tolist())
        if estimate is not None:
            floors[row] = estimate
            has_floor[row] = True
    return floors, has_floor
