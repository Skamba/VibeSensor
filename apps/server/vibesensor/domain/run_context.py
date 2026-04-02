"""Run-context snapshot carrying analysis settings and optional car context."""

from __future__ import annotations

from dataclasses import dataclass, field

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
