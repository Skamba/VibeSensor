"""Boundary codecs for run-capture setup snapshots."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import ConfigurationSnapshot, TireSpec


def configuration_snapshot_from_metadata(metadata: Mapping[str, object]) -> ConfigurationSnapshot:
    """Decode persisted run metadata into the typed configuration snapshot."""

    tire_spec = TireSpec.from_aspects(
        {
            key: coerced
            for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
            if (value := metadata.get(key)) is not None
            if (coerced := _coerce_float(value)) is not None
        },
        deflection_factor=_coerce_float(metadata.get("tire_deflection_factor", 1.0)) or 1.0,
    )
    return ConfigurationSnapshot(
        sensor_model=_non_empty_text(metadata.get("sensor_model")),
        firmware_version=_non_empty_text(metadata.get("firmware_version")),
        raw_sample_rate_hz=_coerce_float(metadata.get("raw_sample_rate_hz")),
        feature_interval_s=_coerce_float(metadata.get("feature_interval_s")),
        final_drive_ratio=_coerce_float(metadata.get("final_drive_ratio")),
        tire_spec=tire_spec,
        metadata=metadata,
    )


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float | str):
        return float(value)
    return None


def _non_empty_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
