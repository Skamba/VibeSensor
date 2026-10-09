"""Canonical typed diagnostics run input."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame

__all__ = ["DiagnosticsRunInput", "build_diagnostics_run_input", "normalize_run_metadata"]


@dataclass(frozen=True, slots=True)
class DiagnosticsRunInput:
    """One normalized diagnostics run used by the typed analysis core."""

    context: RunMetadata
    samples: tuple[SensorFrame, ...]
    # Each sample's raw window mean per axis (gravity and the car's own
    # acceleration), in sample order; empty without the raw capture.
    window_means: tuple[tuple[float, float, float] | None, ...] = ()

    @property
    def run_id(self) -> str:
        return self.context.run_id


def build_diagnostics_run_input(
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
    *,
    file_name: str = "run",
    window_means: Sequence[tuple[float, float, float] | None] = (),
) -> DiagnosticsRunInput:
    """Normalize typed diagnostics inputs into the canonical run model."""

    context = normalize_run_metadata(metadata, file_name=file_name)
    return DiagnosticsRunInput(
        context=context,
        samples=tuple(samples),
        window_means=tuple(window_means),
    )


def normalize_run_metadata(
    metadata: RunMetadata,
    *,
    file_name: str = "run",
) -> RunMetadata:
    """Ensure diagnostics always sees canonical typed metadata with a run id."""

    return metadata if metadata.run_id else replace(metadata, run_id=f"run-{file_name}")
