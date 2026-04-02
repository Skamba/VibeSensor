"""Diagnostics helpers over the canonical typed run metadata model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from vibesensor.domain import OrderReferenceSpec
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    ScalarSettings,
    analysis_settings_snapshot_items,
)
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = [
    "analysis_settings_items",
    "current_gear_ratio",
    "effective_order_reference_spec",
    "final_drive_ratio",
    "prepare_diagnostics_metadata",
    "reference_complete",
]


def prepare_diagnostics_metadata(
    metadata: RunMetadata | Mapping[str, object],
    *,
    file_name: str = "run",
) -> RunMetadata:
    """Decode boundary metadata once and guarantee the diagnostics run id."""

    typed_metadata = (
        metadata if isinstance(metadata, RunMetadata) else run_metadata_from_mapping(metadata)
    )
    run_id = typed_metadata.run_id or f"run-{file_name}"
    return typed_metadata if typed_metadata.run_id else replace(typed_metadata, run_id=run_id)


def analysis_settings_items(metadata: RunMetadata) -> ScalarSettings:
    """Flatten analysis settings for report/test-run boundaries."""

    return analysis_settings_snapshot_items(metadata.analysis_settings)


def effective_order_reference_spec(
    metadata: RunMetadata,
    sample: SensorFrame | None = None,
) -> OrderReferenceSpec | None:
    """Return the base order-reference spec with optional per-sample ratio overrides."""

    spec = metadata.order_reference_spec
    if sample is None or spec is None:
        return spec
    final_drive = sample.final_drive_ratio
    gear_ratio = sample.gear
    if final_drive is None and gear_ratio is None:
        return spec
    return replace(
        spec,
        final_drive_ratio=final_drive if final_drive is not None else spec.final_drive_ratio,
        current_gear_ratio=gear_ratio if gear_ratio is not None else spec.current_gear_ratio,
    )


def final_drive_ratio(metadata: RunMetadata) -> float | None:
    spec = metadata.order_reference_spec
    if spec is not None and spec.final_drive_ratio > 0:
        return spec.final_drive_ratio
    ratio = metadata.analysis_settings.final_drive_ratio
    return ratio if ratio > 0 else None


def current_gear_ratio(metadata: RunMetadata) -> float | None:
    spec = metadata.order_reference_spec
    if spec is not None and spec.current_gear_ratio > 0:
        return spec.current_gear_ratio
    ratio = metadata.analysis_settings.current_gear_ratio
    return ratio if ratio > 0 else None


def reference_complete(metadata: RunMetadata) -> bool:
    """Return whether enough metadata exists for order-reference analysis."""

    spec = metadata.order_reference_spec
    return bool(
        metadata.raw_sample_rate_hz
        and metadata.tire_circumference_m
        and spec is not None
        and spec.is_complete
        and (metadata.explicit_engine_rpm is not None or spec.has_engine_reference)
    )
