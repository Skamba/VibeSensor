"""Decoding helpers for diagnostics context construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata

from ._context import DiagnosticsContext


def build_diagnostics_context(
    metadata: RunMetadata | Mapping[str, object],
    *,
    file_name: str = "run",
) -> DiagnosticsContext:
    """Build the canonical diagnostics context from typed run metadata."""

    typed_metadata = metadata if isinstance(metadata, RunMetadata) else run_metadata_from_mapping(metadata)
    run_id = typed_metadata.run_id or f"run-{file_name}"
    typed_metadata = typed_metadata if typed_metadata.run_id else replace(typed_metadata, run_id=run_id)
    return DiagnosticsContext(metadata=typed_metadata)
