"""Canonical typed diagnostics run input."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

from ._metadata import prepare_diagnostics_metadata

__all__ = ["DiagnosticsRunInput", "build_diagnostics_run_input"]


@dataclass(frozen=True, slots=True)
class DiagnosticsRunInput:
    """One normalized diagnostics run used by the typed analysis core."""

    context: RunMetadata
    samples: tuple[SensorFrame, ...]

    @property
    def metadata(self) -> RunMetadata:
        return self.context

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
        context=prepare_diagnostics_metadata(metadata, file_name=file_name),
        samples=tuple(samples),
    )
