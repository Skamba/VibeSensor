"""Run-loading helpers for diagnostics adapters."""

from __future__ import annotations

from pathlib import Path

from vibesensor.shared.boundaries.run_log import read_jsonl_run
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame


def _load_run(path: Path) -> tuple[RunMetadata, list[SensorFrame], list[str]]:
    """Load one JSONL run and return metadata, samples, and decode warnings."""
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".jsonl":
        raise ValueError(f"Unsupported run format for report: {path.name}")
    run_data = read_jsonl_run(path)
    return run_data.metadata, list(run_data.samples), []
