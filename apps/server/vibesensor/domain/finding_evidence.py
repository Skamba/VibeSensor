"""Supporting value objects for the finding domain model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from vibesensor.coerce import coerce_float
from vibesensor.domain.finding_types import VibrationSource

__all__ = [
    "FindingEvidence",
    "Signature",
]


@dataclass(frozen=True, slots=True)
class FindingEvidence:
    """Structured support for a finding — evidence quality and consistency."""

    match_rate: float = 0.0
    global_match_rate: float | None = None
    focused_speed_band: str | None = None
    mean_relative_error: float | None = None
    mean_noise_floor_db: float | None = None
    possible_samples: int | None = None
    matched_samples: int | None = None
    snr_db: float | None = None
    presence_ratio: float = 0.0
    burstiness: float = 0.0
    spatial_concentration: float = 0.0
    frequency_correlation: float = 0.0
    speed_uniformity: float = 0.0
    spatial_uniformity: float = 0.0
    phases_with_evidence: int | None = None
    phase_confidences: tuple[tuple[str, float], ...] = ()
    vibration_strength_db: float | None = None

    _STRONG_MATCH_RATE: ClassVar[float] = 0.70
    _STRONG_SNR_DB: ClassVar[float] = 6.0
    _CONSISTENT_BURSTINESS: ClassVar[float] = 0.3
    _CONSISTENT_PRESENCE: ClassVar[float] = 0.5
    _WELL_LOCALIZED_CONCENTRATION: ClassVar[float] = 0.6

    @property
    def is_strong(self) -> bool:
        """Evidence is strong enough to support a diagnostic conclusion."""
        return (
            self.match_rate >= self._STRONG_MATCH_RATE
            and self.snr_db is not None
            and self.snr_db >= self._STRONG_SNR_DB
        )

    @property
    def is_consistent(self) -> bool:
        """Evidence is temporally consistent (not bursty/intermittent)."""
        return (
            self.burstiness < self._CONSISTENT_BURSTINESS
            and self.presence_ratio >= self._CONSISTENT_PRESENCE
        )

    @property
    def is_well_localized(self) -> bool:
        """Evidence is spatially concentrated, not diffuse."""
        return self.spatial_concentration >= self._WELL_LOCALIZED_CONCENTRATION

    @classmethod
    def from_metrics(cls, d: Mapping[str, object]) -> FindingEvidence:
        """Construct from a ``FindingEvidenceMetrics`` dict using canonical keys.

        Legacy alias handling (e.g. ``snr_ratio`` → ``snr_db``) is NOT done
        here — boundary callers must pre-normalize before calling this factory.
        """

        def _float(key: str) -> float:
            raw = d.get(key)
            if raw is None:
                return 0.0
            try:
                return coerce_float(raw)
            except (TypeError, ValueError):
                return 0.0

        def _float_or_none(key: str) -> float | None:
            raw = d.get(key)
            if raw is None:
                return None
            try:
                return coerce_float(raw)
            except (TypeError, ValueError):
                return None

        phase_conf = d.get("per_phase_confidence")
        phase_items: tuple[tuple[str, float], ...] = ()
        if isinstance(phase_conf, dict):
            phase_items = tuple(
                (str(k), float(v))
                for k, v in sorted(phase_conf.items())
                if isinstance(v, (int, float))
            )

        return cls(
            match_rate=_float("match_rate"),
            global_match_rate=_float_or_none("global_match_rate"),
            focused_speed_band=(
                str(d.get("focused_speed_band")).strip()
                if d.get("focused_speed_band") is not None
                else None
            ),
            mean_relative_error=_float_or_none("mean_relative_error"),
            mean_noise_floor_db=_float_or_none("mean_noise_floor_db"),
            possible_samples=(
                int(ps) if isinstance((ps := d.get("possible_samples")), (int, float)) else None
            ),
            matched_samples=(
                int(ms) if isinstance((ms := d.get("matched_samples")), (int, float)) else None
            ),
            snr_db=_float_or_none("snr_db"),
            presence_ratio=_float("presence_ratio"),
            burstiness=_float("burstiness"),
            spatial_concentration=_float("spatial_concentration"),
            frequency_correlation=_float("frequency_correlation"),
            speed_uniformity=_float("speed_uniformity"),
            spatial_uniformity=_float("spatial_uniformity"),
            phases_with_evidence=(
                int(pwe)
                if isinstance((pwe := d.get("phases_with_evidence")), (int, float))
                else None
            ),
            phase_confidences=phase_items,
            vibration_strength_db=_float_or_none("vibration_strength_db"),
        )


@dataclass(frozen=True, slots=True)
class Signature:
    """A meaningful vibration pattern label attached to a finding."""

    key: str
    source: VibrationSource
    label: str
    observation_ids: tuple[str, ...] = ()
    support_score: float = 0.0

    @property
    def observation_count(self) -> int:
        return len(self.observation_ids)

    @property
    def is_consistent(self) -> bool:
        return len(self.observation_ids) > 0 and self.support_score > 0.0

    @classmethod
    def from_label(
        cls,
        label: str,
        *,
        source: VibrationSource,
        observation_ids: tuple[str, ...] = (),
        support_score: float = 0.0,
    ) -> Signature:
        key = label.strip().lower().replace("/", "_").replace(" ", "_") or "unknown_signature"
        return cls(
            key=key,
            source=source,
            label=label.strip() or "unknown signature",
            observation_ids=observation_ids,
            support_score=support_score,
        )
