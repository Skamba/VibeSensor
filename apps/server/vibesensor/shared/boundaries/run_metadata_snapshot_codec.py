"""Boundary codec for ``RunMetadataSnapshot``."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import RunMetadataSnapshot
from vibesensor.shared.json_utils import as_float_or_none as _as_float


def run_metadata_snapshot_from_metadata(
    metadata: Mapping[str, object],
    *,
    fallback_run_id: str | None = None,
) -> RunMetadataSnapshot:
    """Decode diagnostics-owned metadata fields from persisted metadata."""

    run_id = _non_empty_text(metadata.get("run_id")) or fallback_run_id or ""
    return RunMetadataSnapshot(
        run_id=run_id,
        case_id=_non_empty_text(metadata.get("case_id")) or "",
        sensor_mac=_non_empty_text(metadata.get("sensor_mac")),
        sensor_model=_non_empty_text(metadata.get("sensor_model")),
        firmware_version=_non_empty_text(metadata.get("firmware_version")),
        raw_sample_rate_hz=_as_float(metadata.get("raw_sample_rate_hz")),
        feature_interval_s=_as_float(metadata.get("feature_interval_s")),
        summary_version=_as_int(metadata.get("_summary_version")) or 1,
    )


def _non_empty_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None
