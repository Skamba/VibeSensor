"""A run's samples as columns (``SampleColumns``): what the post-stop analysis reads of each."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from vibesensor.dsp.window_spectrum import WindowSpectrum

__all__ = [
    "SAMPLE_COLUMN_FIELDS",
    "SampleColumns",
    "coded",
    "first_seen",
    "optional_floats",
    "rows_of_groups",
]

type _Floats = npt.NDArray[np.float64]
type _Codes = npt.NDArray[np.intp]
type _Ints = npt.NDArray[np.int64]

# The ``SensorFrame`` fields the post-stop analysis reads, in stored-column order.
SAMPLE_COLUMN_FIELDS: tuple[str, ...] = (
    "t_s",
    "analysis_window_start_us",
    "analysis_window_end_us",
    "client_id",
    "client_name",
    "location",
    "sample_rate_hz",
    "speed_kmh",
    "speed_source",
    "engine_rpm",
    "engine_rpm_source",
    "gear",
    "final_drive_ratio",
    "accel_x_g",
    "accel_y_g",
    "accel_z_g",
    "vibration_strength_db",
    "strength_bucket",
    "strength_peak_amp_g",
    "strength_floor_amp_g",
    "frames_dropped_total",
    "queue_overflow_drops",
)


@dataclass(frozen=True, slots=True, eq=False)
class SampleColumns:
    """A run's samples (``SensorFrame``) as the post-stop analysis reads them, field by field.

    One entry per sample in each column, in sample order. A float a sample
    does not have is NaN: a stored float is finite or NULL, and the raw replay
    writes one that is not finite as none. A microsecond time is a float too,
    exactly: stored integers are within 2**53. A text field is an index into
    its distinct values; a sample's sensor is its (location code, name, client
    id), and a strength bucket is -1 where it has none (None or empty). The loader leaves the
    spectra none and the raw replay writes those it rebuilds, with their
    samples' readings and strengths, in place.
    """

    sensor_of: _Codes
    sensors: Sequence[tuple[str, str, str]]
    t_s: _Floats
    analysis_window_start_us: _Floats
    analysis_window_end_us: _Floats
    # 0 where unknown.
    sample_rate_hz: _Ints
    speed_kmh: _Floats
    speed_source_of: _Codes
    speed_sources: Sequence[str]
    engine_rpm: _Floats
    engine_rpm_source_of: _Codes
    engine_rpm_sources: Sequence[str]
    gear: _Floats
    final_drive_ratio: _Floats
    accel_x_g: _Floats
    accel_y_g: _Floats
    accel_z_g: _Floats
    vibration_strength_db: _Floats
    strength_bucket_of: _Codes
    strength_buckets: list[str]
    strength_peak_amp_g: _Floats
    strength_floor_amp_g: _Floats
    frames_dropped_total: _Ints
    queue_overflow_drops: _Ints
    spectra: list[WindowSpectrum | None]

    @classmethod
    def from_fields(cls, values: Mapping[str, Sequence[Any]]) -> SampleColumns:
        """The samples whose ``SAMPLE_COLUMN_FIELDS`` are *values* (each as ``SensorFrame`` has it).

        None has a spectrum.
        """
        size = len(values["t_s"])
        sensor_of, sensors = coded(
            list(zip(values["location"], values["client_name"], values["client_id"], strict=True))
        )
        speed_source_of, speed_sources = coded(values["speed_source"])
        engine_rpm_source_of, engine_rpm_sources = coded(values["engine_rpm_source"])
        strength_bucket_of, strength_buckets = _coded_or_none(values["strength_bucket"])
        return cls(
            sensor_of=sensor_of,
            sensors=sensors,
            t_s=_floats(values["t_s"]),
            analysis_window_start_us=_floats(values["analysis_window_start_us"]),
            analysis_window_end_us=_floats(values["analysis_window_end_us"]),
            sample_rate_hz=np.array(
                [rate or 0 for rate in values["sample_rate_hz"]], dtype=np.int64
            ),
            speed_kmh=_floats(values["speed_kmh"]),
            speed_source_of=speed_source_of,
            speed_sources=speed_sources,
            engine_rpm=_floats(values["engine_rpm"]),
            engine_rpm_source_of=engine_rpm_source_of,
            engine_rpm_sources=engine_rpm_sources,
            gear=_floats(values["gear"]),
            final_drive_ratio=_floats(values["final_drive_ratio"]),
            accel_x_g=_floats(values["accel_x_g"]),
            accel_y_g=_floats(values["accel_y_g"]),
            accel_z_g=_floats(values["accel_z_g"]),
            vibration_strength_db=_floats(values["vibration_strength_db"]),
            strength_bucket_of=strength_bucket_of,
            strength_buckets=strength_buckets,
            strength_peak_amp_g=_floats(values["strength_peak_amp_g"]),
            strength_floor_amp_g=_floats(values["strength_floor_amp_g"]),
            frames_dropped_total=np.array(values["frames_dropped_total"], dtype=np.int64),
            queue_overflow_drops=np.array(values["queue_overflow_drops"], dtype=np.int64),
            spectra=[None] * size,
        )

    def __len__(self) -> int:
        return int(self.t_s.size)

    def subset(self, rows: npt.NDArray[np.intp]) -> SampleColumns:
        """The samples at *rows*, with the same distinct text values."""
        return SampleColumns(
            sensor_of=self.sensor_of[rows],
            sensors=self.sensors,
            t_s=self.t_s[rows],
            analysis_window_start_us=self.analysis_window_start_us[rows],
            analysis_window_end_us=self.analysis_window_end_us[rows],
            sample_rate_hz=self.sample_rate_hz[rows],
            speed_kmh=self.speed_kmh[rows],
            speed_source_of=self.speed_source_of[rows],
            speed_sources=self.speed_sources,
            engine_rpm=self.engine_rpm[rows],
            engine_rpm_source_of=self.engine_rpm_source_of[rows],
            engine_rpm_sources=self.engine_rpm_sources,
            gear=self.gear[rows],
            final_drive_ratio=self.final_drive_ratio[rows],
            accel_x_g=self.accel_x_g[rows],
            accel_y_g=self.accel_y_g[rows],
            accel_z_g=self.accel_z_g[rows],
            vibration_strength_db=self.vibration_strength_db[rows],
            strength_bucket_of=self.strength_bucket_of[rows],
            strength_buckets=list(self.strength_buckets),
            strength_peak_amp_g=self.strength_peak_amp_g[rows],
            strength_floor_amp_g=self.strength_floor_amp_g[rows],
            frames_dropped_total=self.frames_dropped_total[rows],
            queue_overflow_drops=self.queue_overflow_drops[rows],
            spectra=[self.spectra[row] for row in rows.tolist()],
        )

    def clients(self) -> tuple[_Codes, list[str]]:
        """Each sample's sensor's client id, as an index into the client ids.

        The client ids come in the order a pass over the samples meets them in.
        """
        client_of_sensor, client_ids = coded(
            [client_id for _location, _name, client_id in self.sensors]
        )
        return first_seen(client_of_sensor[self.sensor_of], client_ids)

    def set_strength_buckets(self, rows: Sequence[int], buckets: Sequence[str | None]) -> None:
        """Set the strength bucket of the samples at *rows* to *buckets* in turn (None: none)."""
        index = {bucket: code for code, bucket in enumerate(self.strength_buckets)}
        for row, bucket in zip(rows, buckets, strict=True):
            if not bucket:
                self.strength_bucket_of[row] = -1
                continue
            code = index.get(bucket)
            if code is None:
                code = index[bucket] = len(self.strength_buckets)
                self.strength_buckets.append(bucket)
            self.strength_bucket_of[row] = code


def coded[T](values: Sequence[T]) -> tuple[npt.NDArray[np.intp], list[T]]:
    """Each of *values* as an index into the distinct values, which come in first-seen order."""
    names: dict[T, int] = {}
    codes = np.array([names.setdefault(value, len(names)) for value in values], dtype=np.intp)
    return codes, list(names)


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


def rows_of_groups(group_of: npt.NDArray[np.intp], count: int) -> list[npt.NDArray[np.intp]]:
    """The rows of each of *count* groups (ascending), by each row's group (-1 for none)."""
    if not count:
        return []
    order = np.argsort(group_of, kind="stable")
    sizes = np.bincount(group_of[group_of >= 0], minlength=count)
    grouped = order[order.size - int(sizes.sum()) :]
    return np.split(grouped, np.cumsum(sizes)[:-1].tolist())


def optional_floats(values: _Floats) -> list[float | None]:
    """*values* as Python floats, None where NaN: a ``SensorFrame`` field's values."""
    found = values.astype(object)
    found[np.isnan(values)] = None
    return cast("list[float | None]", found.tolist())


def _coded_or_none(values: Sequence[str | None]) -> tuple[npt.NDArray[np.intp], list[str]]:
    """Each of *values* as an index into the distinct ones (first-seen order); -1 for none.

    None and an empty text are none.
    """
    names: dict[str, int] = {}
    codes = np.array(
        [names.setdefault(value, len(names)) if value else -1 for value in values],
        dtype=np.intp,
    )
    return codes, list(names)


def _floats(values: Sequence[float | int | None]) -> _Floats:
    """*values* as floats, NaN where None."""
    return np.array(values, dtype=np.float64)
