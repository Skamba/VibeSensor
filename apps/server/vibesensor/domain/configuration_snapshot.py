"""Immutable diagnostic configuration captured for a case stage or test run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from vibesensor.domain.car import TireSpec

__all__ = ["ConfigurationSnapshot"]


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    """Vehicle/setup state relevant for interpreting a run."""

    sensor_model: str | None = None
    firmware_version: str | None = None
    raw_sample_rate_hz: float | None = None
    feature_interval_s: float | None = None
    final_drive_ratio: float | None = None
    tire_spec: TireSpec | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, object]) -> ConfigurationSnapshot:
        def _coerce_float(value: object) -> float | None:
            if isinstance(value, bool):
                return float(value)
            if isinstance(value, int | float | str):
                return float(value)
            return None

        tire_spec = TireSpec.from_aspects(
            {
                key: coerced
                for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
                if (value := metadata.get(key)) is not None
                if (coerced := _coerce_float(value)) is not None
            },
            deflection_factor=_coerce_float(metadata.get("tire_deflection_factor", 1.0)) or 1.0,
        )

        def _as_float(key: str) -> float | None:
            return _coerce_float(metadata.get(key))

        return cls(
            sensor_model=str(metadata.get("sensor_model") or "").strip() or None,
            firmware_version=str(metadata.get("firmware_version") or "").strip() or None,
            raw_sample_rate_hz=_as_float("raw_sample_rate_hz"),
            feature_interval_s=_as_float("feature_interval_s"),
            final_drive_ratio=_as_float("final_drive_ratio"),
            tire_spec=tire_spec,
            metadata=metadata,
        )
