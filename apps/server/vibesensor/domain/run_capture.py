"""Immutable captured evidence from one completed Run."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.measurement import Measurement
from vibesensor.domain.run_setup import RunSetup

__all__ = ["RunCapture"]


@dataclass(frozen=True, slots=True)
class RunCapture:
    """Immutable captured evidence from one completed Run.

    RunCapture is the bridge between capture lifecycle (Run) and analyzed
    diagnostic meaning (TestRun). It holds captured evidence and setup
    context, interpreted within the case-scoped Car context.

    Note: ``measurements`` defaults to an empty tuple. The analysis pipeline
    works with raw numpy arrays for DSP performance; converting thousands of
    samples to Measurement domain objects is prohibitively expensive and
    currently has no consumer. The structural relationship exists but is not
    populated for performance reasons.
    """

    run_id: str
    setup: RunSetup = RunSetup()
    analysis_settings: tuple[tuple[str, int | float | bool | str], ...] = ()
    measurements: tuple[Measurement, ...] = ()
    sample_count: int = 0
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("RunCapture.run_id must be non-empty")
