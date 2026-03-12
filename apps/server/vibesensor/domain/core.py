"""Core domain models — value objects, aggregate roots, and primary domain concepts.

This module is the single source of domain-level abstractions for vibration
diagnostics.  All classes are plain Python dataclasses with **no** dependency
on FastAPI, UDP sockets, or database layers.

Primary domain concepts
-----------------------
The ten foundational domain objects are:

1. ``Car`` – the vehicle under test.
2. ``Sensor`` – a physical accelerometer node.
3. ``SensorPlacement`` – a sensor's mounting position on the vehicle.
4. ``Run`` – one complete diagnostic measurement session (aggregate root).
5. ``Measurement`` – a single multi-axis acceleration sample (value object).
6. ``SpeedSource`` – how vehicle speed is obtained during a run.
7. ``AnalysisWindow`` – a contiguous aligned chunk of samples for analysis.
8. ``Finding`` – one diagnostic conclusion or cause candidate.
9. ``Report`` – the assembled output of a diagnostic run.
10. ``HistoryRecord`` – a persisted run with its analysis results.

``DiagnosticSession`` and ``AccelerationSample`` remain as compatibility
aliases for ``Run`` and ``Measurement`` respectively.

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
from typing import Literal

from vibesensor.strength_bands import bucket_for_strength
from vibesensor.vibration_strength import vibration_strength_db_scalar

__all__ = [
    # Primary domain names
    "AnalysisWindow",
    "Car",
    "Finding",
    "HistoryRecord",
    "Measurement",
    "Report",
    "Run",
    "Sensor",
    "SensorPlacement",
    "SpeedSource",
    "SpeedSourceKind",
    # Existing names (kept for backward compatibility)
    "AccelerationSample",
    "DiagnosticSession",
    "SessionStatus",
    "VibrationReading",
]

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

SpeedSourceKind = Literal["gps", "obd2", "manual"]


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

    # -- factory methods ----------------------------------------------------

    @staticmethod
    def compute_db(peak_amplitude_g: float, noise_floor_g: float) -> float:
        """Compute vibration strength in dB from amplitude pair.

        Uses the canonical formula:
        ``20 × log₁₀((peak + ε) / (floor + ε))``
        where ``ε = max(1e-9, floor × 0.05)``.

        This is a convenience entry point for code that has pre-computed
        amplitude values but does not need a full ``VibrationReading``
        object (e.g. aggregate statistics in the analysis pipeline).
        """
        return vibration_strength_db_scalar(
            peak_band_rms_amp_g=peak_amplitude_g,
            floor_amp_g=noise_floor_g,
        )

    @staticmethod
    def compute_db_or_none(
        peak_amplitude_g: float | None,
        noise_floor_g: float | None,
    ) -> float | None:
        """Like :meth:`compute_db` but returns ``None`` when either input is ``None``."""
        if peak_amplitude_g is None or noise_floor_g is None:
            return None
        return vibration_strength_db_scalar(
            peak_band_rms_amp_g=peak_amplitude_g,
            floor_amp_g=noise_floor_g,
        )


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


# ---------------------------------------------------------------------------
# Phase 1: Primary domain aliases for already-good concepts
# ---------------------------------------------------------------------------

# ``Measurement`` is the primary domain name for a single acceleration
# sample.  ``AccelerationSample`` remains for backward compatibility.
Measurement = AccelerationSample

# ``Run`` is the primary domain name for a diagnostic session.
# ``DiagnosticSession`` remains for backward compatibility.
Run = DiagnosticSession


# ---------------------------------------------------------------------------
# Phase 2: Enriched domain objects — Car, Sensor, SensorPlacement
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpeedSource:
    """How vehicle speed is obtained during a diagnostic run.

    Wraps speed-source identity (GPS / OBD2 / manual), optional manual
    override, and fallback policy.  Configuration details (stale timeouts,
    OBD2 parameters) remain in ``SpeedSourceConfig`` which acts as the
    persistence/config adapter.
    """

    kind: SpeedSourceKind = "gps"
    manual_speed_kmh: float | None = None
    fallback_mode: str = "manual"

    # -- queries -----------------------------------------------------------

    @property
    def is_manual(self) -> bool:
        return self.kind == "manual"

    @property
    def is_gps(self) -> bool:
        return self.kind == "gps"

    @property
    def label(self) -> str:
        """Human-readable label for this speed source."""
        labels = {"gps": "GPS", "obd2": "OBD-II", "manual": "Manual"}
        return labels.get(self.kind, self.kind.upper())


@dataclass(frozen=True, slots=True)
class SensorPlacement:
    """A sensor's mounting position on the vehicle.

    Replaces stringly-typed location handling with a first-class value
    object that carries identity, classification, and display helpers.

    ``code`` is the canonical location code (e.g. ``"front_left_wheel"``).
    ``label`` is the human-readable display name (e.g. ``"Front Left Wheel"``).
    """

    code: str
    label: str = ""

    # -- classification ----------------------------------------------------

    _WHEEL_CODES: frozenset[str] = frozenset(
        {
            "front_left_wheel",
            "front_right_wheel",
            "rear_left_wheel",
            "rear_right_wheel",
        },
    )

    @property
    def is_wheel(self) -> bool:
        """Whether this placement is on a wheel/corner position."""
        return self.code in self._WHEEL_CODES

    @property
    def display_name(self) -> str:
        """Human-readable name, falling back to the code if no label is set."""
        return self.label or self.code.replace("_", " ").title()

    # -- factory methods ---------------------------------------------------

    @classmethod
    def from_code(cls, code: str) -> SensorPlacement:
        """Create a placement from a canonical location code.

        Resolves the human-readable label from the location code registry
        (``vibesensor.locations.LOCATION_CODES``).  Falls back to a
        title-cased version of the code if the code is not found.
        """
        from vibesensor.locations import LOCATION_CODES

        label = LOCATION_CODES.get(code, code.replace("_", " ").title())
        return cls(code=code, label=label)


@dataclass(frozen=True, slots=True)
class Sensor:
    """A physical accelerometer node attached to the vehicle.

    Owns identity (MAC-based ``sensor_id``), user-assigned name, and
    the placement where the sensor is mounted.  Configuration and
    persistence details remain in ``SensorConfig``.
    """

    sensor_id: str
    name: str = ""
    placement: SensorPlacement | None = None

    # -- queries -----------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Human-readable sensor name, falling back to sensor_id."""
        return self.name or self.sensor_id

    @property
    def location_code(self) -> str:
        """Shortcut to the placement code, or empty string if unplaced."""
        return self.placement.code if self.placement else ""

    @property
    def is_placed(self) -> bool:
        """Whether this sensor has an assigned placement."""
        return self.placement is not None and bool(self.placement.code)


@dataclass(frozen=True, slots=True)
class Car:
    """The vehicle under test.

    Owns identity, user-facing name, vehicle type, and geometry aspects
    (tire dimensions, gear ratios) that drive order analysis.
    Configuration and persistence details remain in ``CarConfig``.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Unnamed Car"
    car_type: str = "sedan"
    aspects: dict[str, float] = field(default_factory=dict)
    variant: str | None = None

    # -- queries -----------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Human-readable name with optional type suffix."""
        if self.car_type and self.car_type != "sedan":
            return f"{self.name} ({self.car_type})"
        return self.name

    @property
    def tire_width_mm(self) -> float | None:
        return self.aspects.get("tire_width_mm")

    @property
    def tire_aspect_pct(self) -> float | None:
        return self.aspects.get("tire_aspect_pct")

    @property
    def rim_in(self) -> float | None:
        """Rim diameter in inches (aspects key ``rim_in``)."""
        return self.aspects.get("rim_in")


# ---------------------------------------------------------------------------
# Phase 3: Introduced domain objects — AnalysisWindow, Finding, Report,
#           HistoryRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisWindow:
    """A contiguous aligned chunk of samples used by the analysis pipeline.

    Represents the temporal and phase context of one analysis unit —
    a segment of the run where driving conditions are sufficiently
    uniform for meaningful spectral and order analysis.
    """

    start_idx: int
    end_idx: int
    phase: str = ""
    start_time_s: float | None = None
    end_time_s: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None

    # -- queries -----------------------------------------------------------

    @property
    def sample_count(self) -> int:
        """Number of samples in this window."""
        return max(0, self.end_idx - self.start_idx)

    @property
    def duration_s(self) -> float | None:
        """Duration of the window in seconds, or None if timestamps are missing."""
        if self.start_time_s is not None and self.end_time_s is not None:
            return self.end_time_s - self.start_time_s
        return None


@dataclass(frozen=True, slots=True)
class Finding:
    """One diagnostic conclusion or cause candidate from analysis.

    This is the first-class domain object for a finding. The existing
    ``Finding`` TypedDict in ``analysis._types`` remains as the
    serialization/payload shape; this domain object provides typed
    access and behavior.

    ``finding_id`` is assigned during finalization (``F001``, ``F002``, …).
    ``suspected_source`` identifies the mechanical component suspected of
    causing the vibration (e.g. ``"wheel_bearing"``, ``"driveshaft"``).
    """

    finding_id: str = ""
    suspected_source: str = ""
    confidence: float | None = None
    frequency_hz: float | None = None
    order: str = ""
    severity: str = ""
    strongest_location: str | None = None
    strongest_speed_band: str | None = None
    peak_classification: str = ""

    # -- classification ----------------------------------------------------

    @property
    def is_reference(self) -> bool:
        """Whether this is a reference-data finding (``REF_*``)."""
        return self.finding_id.strip().upper().startswith("REF_")

    @property
    def is_informational(self) -> bool:
        return self.severity.strip().lower() == "info"

    @property
    def is_diagnostic(self) -> bool:
        return not self.is_reference and not self.is_informational

    @property
    def confidence_pct(self) -> int | None:
        """Confidence as integer percentage, or None if unset."""
        if self.confidence is None:
            return None
        return round(self.confidence * 100)

    @property
    def source_normalized(self) -> str:
        """Lower-cased, stripped suspected source for comparison."""
        return self.suspected_source.strip().lower()


@dataclass(frozen=True, slots=True)
class Report:
    """The assembled output of a diagnostic run.

    This is the primary domain object for a rendered or ready-to-render
    report.  ``ReportTemplateData`` in ``report.report_data`` remains as
    the PDF-rendering adapter.
    """

    run_id: str
    title: str = ""
    lang: str = "en"
    car_name: str | None = None
    car_type: str | None = None
    date_str: str = ""
    duration_text: str | None = None
    sample_count: int = 0
    sensor_count: int = 0
    finding_count: int = 0


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    """A persisted run with its analysis results.

    This is the primary domain object for a completed or in-progress run
    stored in the history database.  The ``HistoryRunPayload`` and
    ``HistoryRunListEntryPayload`` TypedDicts in ``backend_types`` remain
    as API transport adapters.
    """

    run_id: str
    status: str = ""
    start_time_utc: str = ""
    end_time_utc: str | None = None
    sample_count: int = 0
    error_message: str | None = None
    analysis_version: int | None = None

    # -- queries -----------------------------------------------------------

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"

    @property
    def is_recording(self) -> bool:
        return self.status == "recording"

    @property
    def has_error(self) -> bool:
        return self.status == "error"

    @property
    def is_analyzable(self) -> bool:
        """Whether this record can be (re)analyzed."""
        return self.status in ("complete", "error") and self.sample_count > 0
