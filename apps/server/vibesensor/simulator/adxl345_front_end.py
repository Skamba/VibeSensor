"""The ADXL345 as the firmware configures it: what the sensor adds to the vibration it reads.

``firmware/esp/lib/adxl345`` sets full resolution at +/-16 g (13 bits, 3.9 mg
per count) and an output data rate equal to the declared sample rate. The
datasheet (Analog Devices ADXL345 Rev. G, Table 1 and Table 7) gives:

- noise 0.75 LSB rms on x/y and 1.1 LSB rms on z at 100 Hz ODR (50 Hz
  bandwidth); it grows with the square root of the bandwidth;
- 0 g offset up to +/-150 mg (x/y) and +/-250 mg (z);
- bandwidth ODR/2 from its internal digital filter, and nothing more: content
  above ODR/2 is attenuated only by that filter's roll-off and folds back into
  the band (no analog anti-alias filter);
- the output clips at the 13-bit range, -4096..4095 counts.

The datasheet gives only the -3 dB point of the internal filter, not its
order; the front end takes the gentlest reading, a first-order roll-off.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vibesensor.ingest.sensor_units import ADXL345_SCALE_G_PER_LSB

__all__ = ["Adxl345FrontEnd"]

_FULL_RES_MIN_COUNT = -4096
_FULL_RES_MAX_COUNT = 4095
_NOISE_LSB_RMS_AT_100HZ_ODR = np.asarray((0.75, 0.75, 1.1))
_DATASHEET_NOISE_BANDWIDTH_HZ = 50.0
# Offsets drawn so the datasheet's limits sit at three standard deviations.
_OFFSET_MG_SIGMA = np.asarray((50.0, 50.0, 250.0 / 3.0))
_COUNTS_PER_G = 1.0 / ADXL345_SCALE_G_PER_LSB


@dataclass(frozen=True, slots=True)
class Adxl345FrontEnd:
    """One sensor's front end: its output data rate and its own 0 g offset (counts).

    The sensor is mounted with z vertical, so gravity reads +1 g on z.
    """

    sample_rate_hz: int
    offset_counts: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @classmethod
    def for_sensor(cls, sample_rate_hz: int, rng: np.random.Generator) -> Adxl345FrontEnd:
        """A front end with an offset drawn within the datasheet's limits."""
        offset_mg = rng.normal(0.0, _OFFSET_MG_SIGMA)
        counts = offset_mg / 1000.0 * _COUNTS_PER_G
        return cls(sample_rate_hz, (float(counts[0]), float(counts[1]), float(counts[2])))

    def tone_gain(self, hz: float) -> float:
        """Magnitude response of the internal filter at *hz* (first order, -3 dB at ODR/2)."""
        return float(1.0 / np.sqrt(1.0 + (hz / (0.5 * self.sample_rate_hz)) ** 2))

    def noise_counts_rms(self) -> np.ndarray:
        """Per-axis noise (counts rms) over the full ODR/2 bandwidth."""
        bandwidth_hz = 0.5 * self.sample_rate_hz
        rms: np.ndarray = _NOISE_LSB_RMS_AT_100HZ_ODR * np.sqrt(
            bandwidth_hz / _DATASHEET_NOISE_BANDWIDTH_HZ
        )
        return rms

    def read(self, counts: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """The ``(n, 3)`` int16 samples the sensor outputs for an acceleration in counts.

        Adds gravity, the offset and the sensor's own noise, rounds to whole
        counts and clips at the full-resolution range.
        """
        out = np.asarray(counts, dtype=np.float64) + np.asarray(self.offset_counts)
        out[:, 2] += _COUNTS_PER_G
        out += rng.normal(0.0, 1.0, size=out.shape) * self.noise_counts_rms()
        samples: np.ndarray = np.clip(np.rint(out), _FULL_RES_MIN_COUNT, _FULL_RES_MAX_COUNT)
        return samples.astype(np.int16)
