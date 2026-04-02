"""Canonical typed diagnostics run input."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

from .context import DiagnosticsContext
from .context_codec import diagnostics_context_from_metadata

__all__ = ["DiagnosticsRunInput", "build_diagnostics_run_input"]


@dataclass(frozen=True, slots=True)
class DiagnosticsRunInput:
    """One normalized diagnostics run used by the typed analysis core."""

    context: DiagnosticsContext
    samples: tuple[SensorFrame, ...]

    @property
    def run_id(self) -> str:
        return self.context.run_id


def build_diagnostics_run_input(
    metadata: RunMetadata | Mapping[str, object],
    samples: Sequence[SensorFrame],
    *,
    file_name: str = "run",
) -> DiagnosticsRunInput:
    """Normalize typed diagnostics inputs into the canonical run model."""

    return DiagnosticsRunInput(
        context=diagnostics_context_from_metadata(metadata, file_name=file_name),
        samples=tuple(samples),
    )
