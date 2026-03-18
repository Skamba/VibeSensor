"""Order-match observation — typed internal frequency-domain match record."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["OrderMatchObservation"]

_CLOSE_MATCH_THRESHOLD = 0.05  # 5% relative error


@dataclass(frozen=True, slots=True)
class OrderMatchObservation:
    """A single frequency-domain order/reference match observation.

    Records the predicted vs observed frequency at a given time and speed,
    with amplitude and spatial location context.
    """

    predicted_hz: float
    matched_hz: float
    rel_error: float
    amp: float
    location: str
    t_s: float | None = None
    speed_kmh: float | None = None
    phase: str | None = None

    def __post_init__(self) -> None:
        if self.predicted_hz <= 0:
            raise ValueError("predicted_hz must be > 0")
        if self.rel_error < 0:
            raise ValueError("rel_error must be >= 0")

    @property
    def is_close_match(self) -> bool:
        """Whether this observation is a close frequency match."""
        return self.rel_error <= _CLOSE_MATCH_THRESHOLD

    @property
    def frequency_error_hz(self) -> float:
        """Absolute frequency error in Hz."""
        return abs(self.predicted_hz - self.matched_hz)

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OrderMatchObservation:
        """Parse from a raw dict, tolerating missing keys for historical data."""

        def _opt_float(key: str) -> float | None:
            v = raw.get(key)
            if v is None:
                return None
            try:
                return float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        def _float(key: str, default: float = 0.0) -> float:
            v = raw.get(key)
            if v is None:
                return default
            try:
                return float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        return cls(
            predicted_hz=_float("predicted_hz"),
            matched_hz=_float("matched_hz"),
            rel_error=_float("rel_error"),
            amp=_float("amp"),
            location=str(raw.get("location", "")),
            t_s=_opt_float("t_s"),
            speed_kmh=_opt_float("speed_kmh"),
            phase=str(raw["phase"]) if raw.get("phase") is not None else None,
        )
