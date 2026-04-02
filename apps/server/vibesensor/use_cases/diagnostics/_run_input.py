"""Canonical typed diagnostics run input."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = ["DiagnosticsRunInput", "build_diagnostics_run_input", "normalize_run_metadata"]


@dataclass(frozen=True, slots=True)
class DiagnosticsRunInput:
    """One normalized diagnostics run used by the typed analysis core."""

    context: RunMetadata
    samples: tuple[SensorFrame, ...]

    @property
    def run_id(self) -> str:
        return self.context.run_id


def build_diagnostics_run_input(
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
    *,
    file_name: str = "run",
) -> DiagnosticsRunInput:
    """Normalize typed diagnostics inputs into the canonical run model."""

    context = normalize_run_metadata(metadata, file_name=file_name)
    return DiagnosticsRunInput(
        context=context,
        samples=tuple(samples),
    )


def normalize_run_metadata(
    metadata: RunMetadata,
    *,
    file_name: str = "run",
) -> RunMetadata:
    """Ensure diagnostics always sees canonical typed metadata with a run id."""

    return metadata if metadata.run_id else replace(metadata, run_id=f"run-{file_name}")
