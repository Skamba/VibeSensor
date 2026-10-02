"""Focused projections from canonical run metadata into analysis settings items."""

from __future__ import annotations

from vibesensor.recording.run_schema import RunMetadata
from vibesensor.settings.analysis_settings_codec import (
    ScalarSettings,
    analysis_settings_snapshot_items,
)

__all__ = [
    "metadata_analysis_settings_items",
]


def metadata_analysis_settings_items(metadata: RunMetadata) -> ScalarSettings:
    """Flatten analysis settings only at the test-run/report boundary."""

    return analysis_settings_snapshot_items(metadata.analysis_settings)
