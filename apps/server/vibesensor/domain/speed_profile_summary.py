"""Speed-summary snapshot used for reconstruction and interpretation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from ._numeric import coerce_float
from ._snapshot_parse import _bool_or, _int_or

__all__ = ["SpeedProfileSummary"]


@dataclass(frozen=True, slots=True)
class SpeedProfileSummary:
    """Typed internal speed-summary snapshot for reconstruction and
    interpretation support.
    """

    min_kmh: float | None = None
    max_kmh: float | None = None
    mean_kmh: float | None = None
    stddev_kmh: float | None = None
    range_kmh: float | None = None
    steady_speed: bool = False
    sample_count: int = 0

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> SpeedProfileSummary:
        """Parse from flat mapping. Missing keys default sensibly."""

        def _opt_float(key: str) -> float | None:
            v = d.get(key)
            if v is None:
                return None
            try:
                f = coerce_float(v)
            except (TypeError, ValueError):
                return None
            return f if math.isfinite(f) else None

        return cls(
            min_kmh=_opt_float("min_kmh"),
            max_kmh=_opt_float("max_kmh"),
            mean_kmh=_opt_float("mean_kmh"),
            stddev_kmh=_opt_float("stddev_kmh"),
            range_kmh=_opt_float("range_kmh"),
            steady_speed=_bool_or(d, "steady_speed"),
            sample_count=_int_or(d, "sample_count"),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict suitable for JSON / boundary payloads."""
        return {
            "min_kmh": self.min_kmh,
            "max_kmh": self.max_kmh,
            "mean_kmh": self.mean_kmh,
            "stddev_kmh": self.stddev_kmh,
            "range_kmh": self.range_kmh,
            "steady_speed": self.steady_speed,
            "sample_count": self.sample_count,
        }
