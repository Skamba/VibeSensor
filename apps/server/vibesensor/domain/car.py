"""The vehicle under test and car-scoped interpretive context.

``Car`` owns identity, user-facing name, vehicle type, and geometry aspects
(tire dimensions, gear ratios) that drive order analysis. Supporting value
objects now live in dedicated modules: ``tire_spec.py`` owns tire geometry
and ``order_reference.py`` owns order-reference math. ``CarSnapshot`` stays
here as the typed internal car context attached to a run.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from vibesensor.domain.order_reference import OrderReferenceSpec, normalize_order_reference_mapping
from vibesensor.domain.tire_spec import TireSpec

__all__ = [
    "Car",
    "CarSnapshot",
    "OrderReferenceSpec",
    "TireSpec",
]


# ---------------------------------------------------------------------------
# CarSnapshot — typed internal car context attached to a run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CarSnapshot:
    """Typed internal car context attached to a run.

    Not an aggregate — a supporting typed internal object for run-attached
    car interpretation context.
    """

    car_id: str | None = None
    name: str | None = None
    car_type: str | None = None
    variant: str | None = None
    aspects: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.aspects, MappingProxyType):
            object.__setattr__(self, "aspects", MappingProxyType(dict(self.aspects)))

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> CarSnapshot:
        """Parse from a flat mapping. Missing keys default to ``None``/empty."""
        raw_aspects = d.get("aspects")
        aspects: dict[str, float] = {}
        if isinstance(raw_aspects, dict):
            for k, v in raw_aspects.items():
                if isinstance(k, str):
                    try:
                        aspects[k] = float(v)
                    except (TypeError, ValueError):
                        pass
        return cls(
            car_id=_str_or_none(d.get("id") or d.get("car_id")),
            name=_str_or_none(d.get("name")),
            car_type=_str_or_none(d.get("type") or d.get("car_type")),
            variant=_str_or_none(d.get("variant")),
            aspects=aspects,
        )

    def to_dict(self) -> dict[str, object]:
        """Project to a persistence-compatible dict."""
        return {
            "id": self.car_id,
            "name": self.name,
            "type": self.car_type,
            "variant": self.variant,
            "aspects": dict(self.aspects),
        }


def _str_or_none(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


@dataclass(frozen=True, slots=True, init=False)
class Car:
    """The vehicle under test.

    Owns identity, user-facing name, vehicle type, and geometry aspects
    (tire dimensions, gear ratios) that drive order analysis.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Unnamed Car"
    car_type: str = "sedan"
    variant: str | None = None
    order_reference_spec: OrderReferenceSpec | None = field(default=None, repr=False)
    _aspects: Mapping[str, float] = field(
        init=False,
        repr=False,
    )

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str = "Unnamed Car",
        car_type: str = "sedan",
        aspects: Mapping[str, float] | None = None,
        variant: str | None = None,
        order_reference_spec: OrderReferenceSpec | None = None,
    ) -> None:
        object.__setattr__(self, "id", id or uuid.uuid4().hex)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "car_type", car_type)
        object.__setattr__(self, "variant", variant)
        object.__setattr__(self, "order_reference_spec", order_reference_spec)
        object.__setattr__(self, "_aspects", MappingProxyType({}))
        self._normalize_order_reference_state(aspects)

    def _normalize_order_reference_state(
        self,
        aspects: Mapping[str, float] | None,
    ) -> None:
        if not self.name or not self.name.strip():
            object.__setattr__(self, "name", "Unnamed Car")
        normalized_aspects = normalize_order_reference_mapping(aspects or {})
        spec = self.order_reference_spec or OrderReferenceSpec.from_settings(normalized_aspects)
        object.__setattr__(self, "order_reference_spec", spec)
        if spec is not None:
            normalized_aspects = spec.to_settings_dict()
        object.__setattr__(self, "_aspects", MappingProxyType(normalized_aspects))

    @classmethod
    def from_persisted_dict(cls, data: Mapping[str, object]) -> Car:
        """Construct a ``Car`` from a raw persisted dict (e.g., loaded from JSON).

        Fills missing aspects from ``AnalysisSettingsSnapshot.DEFAULTS`` and
        sanitises input values.
        """
        # Lazy import — snapshots.py imports from this module.
        from vibesensor.domain.snapshots import AnalysisSettingsSnapshot

        car_id = str(data.get("id") or str(uuid.uuid4()))
        name = str(data.get("name") or "Unnamed Car").strip()[:64] or "Unnamed Car"
        car_type = str(data.get("type") or "sedan").strip()[:32] or "sedan"
        raw_aspects = data.get("aspects") or {}
        aspects: dict[str, float] = dict(AnalysisSettingsSnapshot.DEFAULTS)
        if isinstance(raw_aspects, dict):
            aspects.update(AnalysisSettingsSnapshot.sanitize(raw_aspects))
        raw_variant = data.get("variant")
        variant = (
            str(raw_variant).strip()[:64] if isinstance(raw_variant, str) and raw_variant else None
        )
        return cls(
            id=car_id,
            name=name,
            car_type=car_type,
            aspects=aspects,
            variant=variant or None,
        )

    @property
    def aspects(self) -> Mapping[str, float]:
        return self._aspects

    # -- queries -----------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Human-readable name with type suffix."""
        if self.car_type:
            return f"{self.name} ({self.car_type})"
        return self.name

    @property
    def tire_spec(self) -> TireSpec | None:
        """Parsed tire dimensions, or ``None`` if incomplete."""
        spec = self.order_reference_spec
        return spec.tire_spec if spec is not None else None

    @property
    def tire_width_mm(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None:
            return spec.tire_spec.width_mm
        return None

    @property
    def tire_aspect_pct(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None:
            return spec.tire_spec.aspect_pct
        return None

    @property
    def rim_in(self) -> float | None:
        """Rim diameter in inches (aspects key ``rim_in``)."""
        spec = self.order_reference_spec
        if spec is not None:
            return spec.tire_spec.rim_in
        return None

    @property
    def tire_circumference_m(self) -> float | None:
        """Compute tire circumference in metres from aspect specs.

        Returns ``None`` if any required dimension is missing or invalid.
        """
        spec = self.order_reference_spec
        return spec.tire_circumference_m if spec is not None else None
