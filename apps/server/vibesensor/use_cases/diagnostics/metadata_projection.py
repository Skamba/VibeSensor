"""Focused projections from canonical run metadata into analysis settings items."""

from __future__ import annotations

from vibesensor.shared.boundaries.codecs import ScalarSettings, analysis_settings_snapshot_items
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "metadata_analysis_settings_items",
]


def metadata_analysis_settings_items(metadata: RunMetadata) -> ScalarSettings:
    """Flatten analysis settings only at the test-run/report boundary."""

    return analysis_settings_snapshot_items(metadata.analysis_settings)
