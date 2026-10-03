"""Immutable captured evidence and setup context for one completed Run.

Co-locates ConfigurationSnapshot, RunSetup and RunCapture — the tightly
coupled value objects that together describe what was measured and how.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vibesensor.domain.sensor import Sensor
from vibesensor.domain.speed_source import SpeedSource
from vibesensor.domain.tire_spec import TireSpec

__all__ = ["ConfigurationSnapshot", "RunCapture", "RunSetup"]


# ---------------------------------------------------------------------------
# ConfigurationSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    """Vehicle/setup state relevant for interpreting a run."""

    sensor_model: str | None = None
    firmware_version: str | None = None
    strength_algorithm_version: str | None = None
    peak_detector_version: str | None = None
    calibration_profile_id: str | None = None
    vehicle_baseline_profile_id: str | None = None
    raw_sample_rate_hz: float | None = None
    feature_interval_s: float | None = None
    final_drive_ratio: float | None = None
    tire_spec: TireSpec | None = None


# ---------------------------------------------------------------------------
# RunSetup
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunSetup:
    """Immutable setup context for one diagnostic run.

    Captures how the run was conducted: which sensors were used, how speed
    was acquired, and firmware/sample-rate configuration.  Does NOT contain
    ``Car`` — car is case-scoped context owned by ``DiagnosticCase``.
    """

    sensors: tuple[Sensor, ...] = ()
    speed_source: SpeedSource = field(default_factory=SpeedSource)
    configuration_snapshot: ConfigurationSnapshot = field(default_factory=ConfigurationSnapshot)


# ---------------------------------------------------------------------------
# RunCapture
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunCapture:
    """Immutable captured evidence from one completed Run.

    RunCapture is the bridge between capture lifecycle (Run) and analyzed
    diagnostic meaning (TestRun). It holds captured evidence and setup
    context, interpreted within the case-scoped Car context.
    Raw samples stay in the DSP/recording subsystem as arrays; they are not
    modelled as per-sample domain objects.
    """

    run_id: str
    setup: RunSetup = field(default_factory=RunSetup)
    analysis_settings: tuple[tuple[str, int | float | bool | str], ...] = ()
    sample_count: int = 0
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("RunCapture.run_id must be non-empty")
