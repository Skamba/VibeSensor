"""Core domain models — value objects and aggregate root.

This module is the single source of domain-level abstractions for vibration
diagnostics.  All classes are plain Python dataclasses with **no** dependency
on FastAPI, UDP sockets, or database layers.

Mathematical contracts
----------------------
* dB conversion uses the canonical formula from
  ``vibesensor.vibration_strength.vibration_strength_db_scalar``:
  ``20 × log₁₀((peak + ε) / (floor + ε))``
  where ``ε = max(1e-9, floor × 0.05)``.

* Severity classification delegates to
  ``vibesensor.strength_bands.bucket_for_strength`` so that threshold
  changes (l0–l5 band boundaries) remain in a single place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from vibesensor.strength_bands import bucket_for_strength
from vibesensor.vibration_strength import vibration_strength_db_scalar

__all__ = [
    "AccelerationSample",
    "DiagnosticSession",
    "SessionStatus",
    "VibrationReading",
]


# ---------------------------------------------------------------------------
# Value Object: AccelerationSample
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccelerationSample:
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


# ---------------------------------------------------------------------------
# Value Object: VibrationReading
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Aggregate Root: DiagnosticSession
# ---------------------------------------------------------------------------


class SessionStatus(StrEnum):
    """Lifecycle states of a :class:`DiagnosticSession`."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass
class DiagnosticSession:
    """Aggregate root for a vibration-diagnostic measurement session.

    Tracks the lifecycle (start / stop) and accumulated readings for one
    diagnostic run.  State fields are modelled after ``run_context.py``
    and ``runlog.py`` metadata.

    Parameters
    ----------
    session_id:
        Unique session identifier (UUID hex string).
    vehicle_id:
        Optional identifier for the vehicle under test.
    analysis_settings:
        Snapshot of analysis settings active at session start.
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    vehicle_id: str | None = None
    analysis_settings: dict[str, float] = field(default_factory=dict)

    status: SessionStatus = field(default=SessionStatus.PENDING, init=False)
    start_time: datetime | None = field(default=None, init=False)
    stop_time: datetime | None = field(default=None, init=False)
    _readings: list[VibrationReading] = field(default_factory=list, init=False, repr=False)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Transition the session to *running* and record the start time.

        Raises
        ------
        RuntimeError
            If the session has already been started or stopped.
        """
        if self.status is not SessionStatus.PENDING:
            raise RuntimeError(
                f"Cannot start session in '{self.status.value}' state; "
                f"expected '{SessionStatus.PENDING.value}'."
            )
        self.status = SessionStatus.RUNNING
        self.start_time = datetime.now(UTC)

    def stop(self) -> None:
        """Transition the session to *stopped* and record the stop time.

        Raises
        ------
        RuntimeError
            If the session is not currently running.
        """
        if self.status is not SessionStatus.RUNNING:
            raise RuntimeError(
                f"Cannot stop session in '{self.status.value}' state; "
                f"expected '{SessionStatus.RUNNING.value}'."
            )
        self.status = SessionStatus.STOPPED
        self.stop_time = datetime.now(UTC)

    # -- sample processing --------------------------------------------------

    def process_sample(
        self,
        sample: AccelerationSample,
        noise_floor: float,
    ) -> VibrationReading:
        """Convert *sample* to a :class:`VibrationReading` and record it.

        Parameters
        ----------
        sample:
            Raw acceleration sample to process.
        noise_floor:
            Estimated noise-floor amplitude in *g*.

        Returns
        -------
        VibrationReading
            The resulting reading (also appended to the session's internal
            list).

        Raises
        ------
        RuntimeError
            If the session is not in the *running* state.
        """
        if self.status is not SessionStatus.RUNNING:
            raise RuntimeError(
                f"Cannot process samples in '{self.status.value}' state; "
                f"session must be '{SessionStatus.RUNNING.value}'."
            )
        reading = sample.to_vibration_reading(noise_floor)
        self._readings.append(reading)
        return reading

    # -- queries ------------------------------------------------------------

    @property
    def readings(self) -> list[VibrationReading]:
        """Return a shallow copy of all recorded readings."""
        return list(self._readings)

    @property
    def reading_count(self) -> int:
        """Return the number of recorded readings."""
        return len(self._readings)

    def get_peak_vibration(self) -> VibrationReading | None:
        """Return the reading with the highest ``intensity_db``, or ``None``.

        Returns
        -------
        VibrationReading | None
            The peak reading, or ``None`` if no readings have been recorded.
        """
        if not self._readings:
            return None
        return max(self._readings, key=lambda r: r.intensity_db)
