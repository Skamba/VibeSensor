"""A run's samples' peaks as flat columns (``SamplePeaks``)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

__all__ = ["SamplePeaks"]


@dataclass(frozen=True, slots=True, eq=False)
class SamplePeaks:
    """Each sample's ranked peaks (``SensorFrame.top_peaks``), all in one set of columns.

    The post-stop analysis reads a sample's peaks here, not from its frame: the
    loader leaves a frame's ``top_peaks`` empty, and the raw replay writes the
    peaks it rebuilds here. Sample by sample, each in rank order: every peak's
    sample, frequency, amplitude and local floor (NaN where it has none), and
    where each sample's run of them starts (one more entry than samples).
    """

    row: npt.NDArray[np.intp]
    hz: npt.NDArray[np.float64]
    amp: npt.NDArray[np.float64]
    local_floor_amp_g: npt.NDArray[np.float64]
    start: npt.NDArray[np.intp]

    @classmethod
    def of_peaks(
        cls,
        rows: Sequence[int] | npt.NDArray[np.intp],
        hz: Sequence[float] | npt.NDArray[np.float64],
        amp: Sequence[float] | npt.NDArray[np.float64],
        local_floor_amp_g: Sequence[float] | npt.NDArray[np.float64],
        size: int,
    ) -> SamplePeaks:
        """The peaks of *size* samples, each given with its sample.

        The samples may come in any order, each one's peaks in rank order.
        """
        row = np.asarray(rows, dtype=np.intp)
        order = np.argsort(row, kind="stable")
        row = row[order]
        start = np.zeros(size + 1, dtype=np.intp)
        np.cumsum(np.bincount(row, minlength=size), out=start[1:])
        return cls(
            row=row,
            hz=np.asarray(hz, dtype=np.float64)[order],
            amp=np.asarray(amp, dtype=np.float64)[order],
            local_floor_amp_g=np.asarray(local_floor_amp_g, dtype=np.float64)[order],
            start=start,
        )

    @classmethod
    def none(cls, size: int) -> SamplePeaks:
        """*size* samples without peaks."""
        return cls.of_peaks([], [], [], [], size)

    @property
    def size(self) -> int:
        """How many samples."""
        return int(self.start.size) - 1

    def rank(self) -> npt.NDArray[np.intp]:
        """Each peak's rank among its sample's (0 for the first)."""
        return np.arange(self.row.size, dtype=np.intp) - self.start[self.row]

    def first_amp(self) -> npt.NDArray[np.float64]:
        """Each sample's first peak's amplitude; NaN where it has none."""
        first = np.full(self.size, np.nan, dtype=np.float64)
        has_peaks = self.start[1:] > self.start[:-1]
        first[has_peaks] = self.amp[self.start[:-1][has_peaks]]
        return first

    def with_peaks_of(self, rows: npt.NDArray[np.intp], other: SamplePeaks) -> SamplePeaks:
        """These peaks and *other*'s, which are those of the samples at *rows* (none here)."""
        return SamplePeaks.of_peaks(
            np.concatenate((self.row, rows[other.row])),
            np.concatenate((self.hz, other.hz)),
            np.concatenate((self.amp, other.amp)),
            np.concatenate((self.local_floor_amp_g, other.local_floor_amp_g)),
            self.size,
        )
