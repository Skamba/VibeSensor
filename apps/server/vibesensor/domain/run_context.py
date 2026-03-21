"""Run-context snapshot carrying analysis settings and optional car context."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from .analysis_settings import AnalysisSettingsSnapshot
from .car import CarSnapshot, OrderReferenceSpec

__all__ = ["RunContextSnapshot"]


@dataclass(frozen=True, slots=True)
class RunContextSnapshot:
    """Run-attached interpretive snapshot containing analysis settings
    and optional car context.
    """

    analysis_settings: AnalysisSettingsSnapshot = field(default_factory=AnalysisSettingsSnapshot)
    car: CarSnapshot | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> RunContextSnapshot:
        """Parse from a nested mapping.

        Expects keys ``"analysis_settings_snapshot"`` and optionally
        ``"active_car_snapshot"``.
        """
        raw_settings = d.get("analysis_settings_snapshot")
        if isinstance(raw_settings, Mapping):
            settings = AnalysisSettingsSnapshot.from_dict(raw_settings)
        else:
            settings = AnalysisSettingsSnapshot()

        raw_car = d.get("active_car_snapshot")
        car: CarSnapshot | None = None
        if isinstance(raw_car, Mapping):
            car = CarSnapshot.from_dict(raw_car)

        return cls(analysis_settings=settings, car=car)

    def to_metadata_dict(self) -> dict[str, object]:
        settings_dict = asdict(self.analysis_settings)
        metadata: dict[str, object] = {
            "analysis_settings_snapshot": {
                key: value
                for key, value in settings_dict.items()
                if isinstance(value, (int, float)) and math.isfinite(float(value))
            },
        }
        if self.car is not None:
            metadata["active_car_snapshot"] = self.car.to_dict()
        return metadata

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        """Convenience — delegates to analysis settings."""
        return self.analysis_settings.order_reference_spec

    @property
    def has_car_context(self) -> bool:
        return self.car is not None

    @property
    def active_car_id(self) -> str | None:
        return self.car.car_id if self.car is not None else None

    @property
    def car_name(self) -> str | None:
        return self.car.name if self.car is not None else None

    @property
    def car_type(self) -> str | None:
        return self.car.car_type if self.car is not None else None

    @property
    def car_variant(self) -> str | None:
        return self.car.variant if self.car is not None else None
