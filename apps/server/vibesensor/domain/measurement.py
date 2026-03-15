"""Value objects for raw acceleration measurements and processed vibration readings.

``Measurement`` is the raw multi-axis sample captured by an ESP32 sensor.

``VibrationReading`` is the dB-expressed result of processing a raw sample
through the vibration-strength pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from vibesensor.strength_bands import bucket_for_strength
from vibesensor.vibration_strength import vibration_strength_db_scalar

__all__ = [
    "Measurement",
    "VibrationReading",
]


@dataclass(frozen=True, slots=True)
class Measurement:
    """A single multi-axis acceleration measurement from an ESP32 sensor.

    Fields mirror the per-sample data carried inside a ``DataMessage`` from
    ``vibesensor.protocol``:

    * **x / y / z**: Acceleration values in *g* (float).  Raw int16 LSB
      values should be converted to *g* before constructing this object.
    * **timestamp**: Measurement time (UTC).
    * **sample_rate_hz**: Sensor sample rate at capture time.
    * **sensor_id**: Hex-encoded 6-byte MAC address of the originating sensor.
    """

    x: float
    y: float
    z: float
    timestamp: datetime
    sample_rate_hz: int
    sensor_id: str = ""

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError(f"sample_rate_hz must be positive, got {self.sample_rate_hz}")

    # -- behaviour ----------------------------------------------------------

    def to_vibration_reading(self, noise_floor: float) -> VibrationReading:
        """Convert this raw sample into a :class:`VibrationReading`.

        Uses the canonical dB formula:
        ``20 × log₁₀((peak_amplitude + ε) / (noise_floor + ε))``
        where ``ε = max(1e-9, noise_floor × 0.05)``.

        The *peak_amplitude* is the Euclidean magnitude of the (x, y, z)
        acceleration vector.

        Parameters
        ----------
        noise_floor:
            Estimated background noise amplitude in *g*.  Typically the P20
            percentile of the combined spectrum (see
            ``vibration_strength.noise_floor_amp_p20_g``).

        Returns
        -------
        VibrationReading
            A processed reading with intensity in dB and the dominant
            frequency set to ``0.0`` (single-sample readings carry no
            frequency information; full spectral analysis is needed for a
            meaningful frequency).
        """
        from math import sqrt

        peak_amplitude = sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

        intensity_db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=peak_amplitude,
            floor_amp_g=noise_floor,
        )

        return VibrationReading(
            timestamp=self.timestamp,
            intensity_db=intensity_db,
            frequency_hz=0.0,
            peak_amplitude_g=peak_amplitude,
            noise_floor_g=noise_floor,
            sensor_id=self.sensor_id,
        )


@dataclass(frozen=True, slots=True)
class VibrationReading:
    """A processed vibration measurement expressed in dB.

    Encapsulates the result of converting raw acceleration data through the
    vibration-strength pipeline.

    * **intensity_db**: Vibration strength in dB (canonical formula).
    * **frequency_hz**: Dominant frequency of the reading (Hz).  ``0.0``
      when derived from a single time-domain sample (no spectral info).
    * **peak_amplitude_g**: RMS amplitude of the peak band in *g*.
    * **noise_floor_g**: Estimated noise floor in *g*.
    """

    timestamp: datetime
    intensity_db: float
    frequency_hz: float
    peak_amplitude_g: float = 0.0
    noise_floor_g: float = 0.0
    sensor_id: str = ""

    # -- behaviour ----------------------------------------------------------

    def get_severity_level(self) -> str:
        """Return the severity band key (``"l0"`` – ``"l5"``) for this reading.

        Delegates to ``vibesensor.strength_bands.bucket_for_strength`` so
        that band thresholds are defined in exactly one place:

        ====  ===========
        Band  Min dB
        ====  ===========
        l0    0.0
        l1    8.0
        l2    16.0
        l3    26.0
        l4    36.0
        l5    46.0
        ====  ===========
        """
        return bucket_for_strength(self.intensity_db)
