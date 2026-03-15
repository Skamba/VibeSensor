"""Canonical setup context for how a diagnostic run was conducted."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.sensing.configuration_snapshot import ConfigurationSnapshot
from vibesensor.domain.sensing.sensor import Sensor
from vibesensor.domain.sensing.speed_source import SpeedSource

__all__ = ["RunSetup"]


@dataclass(frozen=True, slots=True)
class RunSetup:
    """Immutable setup context for one diagnostic run.

    Captures how the run was conducted: which sensors were used, how speed
    was acquired, and firmware/sample-rate configuration.  Does NOT contain
    ``Car`` — car is case-scoped context owned by ``DiagnosticCase``.
    """

    sensors: tuple[Sensor, ...] = ()
    speed_source: SpeedSource = SpeedSource()
    configuration_snapshot: ConfigurationSnapshot = ConfigurationSnapshot()
