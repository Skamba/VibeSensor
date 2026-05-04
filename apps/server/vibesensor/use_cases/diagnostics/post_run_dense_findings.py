"""Dense post-run finding classification from episodes and order bands."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Literal

from vibesensor.domain import Finding, FindingKind, VibrationSource
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.whole_run_json_helpers import set_optional_value
from vibesensor.use_cases.diagnostics.post_run_order_bands import (
    OrderBand,
    OrderBandSource,
    OrderBandWindow,
    PostRunOrderBandTimeline,
)
from vibesensor.use_cases.diagnostics.post_run_vibration_episodes import VibrationEpisode

type DenseConfidenceLabel = Literal["high", "medium", "low"]
type DenseFindingCaveat = Literal[
    "ambiguous_origin",
    "conflicting_sensor_evidence",
    "missing_reference_data",
    "poor_quality",
    "low_usable_duration",
    "transient_only",
    "unmatched_strong_episode",
]

_SOURCE_TO_ORIGIN: Mapping[OrderBandSource, VibrationSource] = {
    "wheel": VibrationSource.WHEEL_TIRE,
    "driveshaft": VibrationSource.DRIVELINE,
    "engine": VibrationSource.ENGINE,
}

__all__ = [
    "DenseConfidenceLabel",
    "DenseFinding",
    "DenseFindingAlternative",
    "DenseFindingCaveat",
    "DenseFindingConfig",
    "DenseFindingEvidenceWindow",
    "classify_post_run_dense_findings",
    "dense_finding_debug_rows",
]


@dataclass(frozen=True, slots=True)
class DenseFindingConfig:
    """Scoring weights and thresholds for dense finding classification."""

    min_match_ratio: float = 0.5
    ambiguity_margin: float = 0.12
    high_confidence_threshold: float = 0.7
    medium_confidence_threshold: float = 0.4
    strong_unknown_strength_db: float = 18.0


@dataclass(frozen=True, slots=True)
class DenseFindingEvidenceWindow:
    """Window-level evidence used by a dense finding classification."""

    window_index: int
    frequency_hz: float
    matched: bool
    band_label: str | None = None
    band_source: OrderBandSource | None = None
    band_min_hz: float | None = None
    band_max_hz: float | None = None
    relative_error: float | None = None

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "window_index": self.window_index,
            "frequency_hz": self.frequency_hz,
            "matched": self.matched,
        }
        set_optional_value(payload, "band_label", self.band_label)
        set_optional_value(payload, "band_source", self.band_source)
        set_optional_value(payload, "band_min_hz", self.band_min_hz)
        set_optional_value(payload, "band_max_hz", self.band_max_hz)
        set_optional_value(payload, "relative_error", self.relative_error)
        return payload


@dataclass(frozen=True, slots=True)
class DenseFindingAlternative:
    """Alternative source hypothesis considered for a dense episode."""

    source: VibrationSource
    score: float
    match_ratio: float
    matched_windows: int
    eligible_windows: int
    best_band_label: str | None = None

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "source": str(self.source),
            "score": self.score,
            "match_ratio": self.match_ratio,
            "matched_windows": self.matched_windows,
            "eligible_windows": self.eligible_windows,
        }
        set_optional_value(payload, "best_band_label", self.best_band_label)
        return payload


@dataclass(frozen=True, slots=True)
class DenseFinding:
    """Reportable dense-analysis finding with confidence and caveats."""

    finding_id: str
    episode_id: str
    likely_origin: VibrationSource
    confidence_score: float
    confidence_label: DenseConfidenceLabel
    evidence_windows: tuple[DenseFindingEvidenceWindow, ...]
    alternatives: tuple[DenseFindingAlternative, ...]
    caveats: tuple[DenseFindingCaveat, ...]
    strongest_location: str | None
    median_frequency_hz: float
    peak_strength_db: float
    duration_s: float
    supporting_window_ids: tuple[int, ...]

    def to_json_object(self) -> JsonObject:
        return {
            "finding_id": self.finding_id,
            "episode_id": self.episode_id,
            "likely_origin": str(self.likely_origin),
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "evidence_windows": [window.to_json_object() for window in self.evidence_windows],
            "alternatives": [alternative.to_json_object() for alternative in self.alternatives],
            "caveats": list(self.caveats),
            "strongest_location": self.strongest_location,
            "median_frequency_hz": self.median_frequency_hz,
            "peak_strength_db": self.peak_strength_db,
            "duration_s": self.duration_s,
            "supporting_window_ids": list(self.supporting_window_ids),
        }

    def to_domain_finding(self) -> Finding:
        order_label = self.alternatives[0].best_band_label if self.alternatives else None
        return Finding(
            finding_id=self.finding_id,
            finding_key=f"dense:{self.episode_id}",
            suspected_source=self.likely_origin,
            confidence=self.confidence_score,
            frequency_hz=self.median_frequency_hz,
            order=order_label or "",
            severity="diagnostic",
            strongest_location=self.strongest_location,
            kind=FindingKind.DIAGNOSTIC,
            ranking_score=self.confidence_score * max(0.0, self.peak_strength_db),
            vibration_strength_db=self.peak_strength_db,
        )


@dataclass(frozen=True, slots=True)
class _SourceScore:
    source: OrderBandSource
    origin: VibrationSource
    score: float
    match_ratio: float
    completeness: float
    matched_windows: int
    eligible_windows: int
    best_band_label: str | None
    evidence_windows: tuple[DenseFindingEvidenceWindow, ...]
    unavailable_count: int


def classify_post_run_dense_findings(
    episodes: Iterable[VibrationEpisode],
    order_bands: PostRunOrderBandTimeline,
    *,
    config: DenseFindingConfig | None = None,
) -> tuple[DenseFinding, ...]:
    """Classify dense vibration episodes against per-window order bands."""

    effective_config = config or DenseFindingConfig()
    _validate_config(effective_config)
    band_windows = {window.window_index: window for window in order_bands.windows}
    findings = tuple(
        _classify_episode(
            episode,
            band_windows=band_windows,
            index=index,
            config=effective_config,
        )
        for index, episode in enumerate(episodes)
    )
    return tuple(
        sorted(
            findings,
            key=lambda finding: (finding.confidence_score, finding.peak_strength_db),
            reverse=True,
        )
    )


def dense_finding_debug_rows(findings: Iterable[DenseFinding]) -> tuple[JsonObject, ...]:
    """Return compact rows for dense finding inspection and golden tests."""

    return tuple(
        {
            "finding_id": finding.finding_id,
            "episode_id": finding.episode_id,
            "likely_origin": str(finding.likely_origin),
            "confidence_score": finding.confidence_score,
            "confidence_label": finding.confidence_label,
            "caveats": list(finding.caveats),
            "evidence_window_count": len(finding.evidence_windows),
        }
        for finding in findings
    )


def _validate_config(config: DenseFindingConfig) -> None:
    for field_name, value in (
        ("min_match_ratio", config.min_match_ratio),
        ("ambiguity_margin", config.ambiguity_margin),
        ("high_confidence_threshold", config.high_confidence_threshold),
        ("medium_confidence_threshold", config.medium_confidence_threshold),
        ("strong_unknown_strength_db", config.strong_unknown_strength_db),
    ):
        if not isfinite(value) or value < 0:
            raise ValueError(f"dense finding config requires {field_name} >= 0")
    if config.min_match_ratio > 1 or config.ambiguity_margin > 1:
        raise ValueError("dense finding ratio thresholds must be <= 1")
    if config.high_confidence_threshold < config.medium_confidence_threshold:
        raise ValueError("high_confidence_threshold must be >= medium_confidence_threshold")


def _classify_episode(
    episode: VibrationEpisode,
    *,
    band_windows: Mapping[int, OrderBandWindow],
    index: int,
    config: DenseFindingConfig,
) -> DenseFinding:
    sources: tuple[OrderBandSource, ...] = ("wheel", "driveshaft", "engine")
    source_scores = tuple(
        _score_source(
            episode,
            source=source,
            band_windows=band_windows,
        )
        for source in sources
    )
    ranked = tuple(sorted(source_scores, key=lambda score: score.score, reverse=True))
    top = ranked[0]
    caveats: list[DenseFindingCaveat] = []
    alternatives = tuple(_alternative(score) for score in ranked if score.eligible_windows > 0)
    likely_origin = top.origin
    confidence_score = top.score
    evidence_windows = top.evidence_windows
    if top.match_ratio < config.min_match_ratio:
        likely_origin = VibrationSource.UNKNOWN_RESONANCE
        confidence_score = _unknown_confidence(episode, top)
        evidence_windows = _unmatched_evidence(episode)
        alternatives = tuple(_alternative(score) for score in ranked)
        if episode.peak_strength_db >= config.strong_unknown_strength_db:
            _append_unique(caveats, "unmatched_strong_episode")
    if len(ranked) > 1 and top.score - ranked[1].score <= config.ambiguity_margin:
        _append_unique(caveats, "ambiguous_origin")
        confidence_score *= 0.85
    if top.completeness < 0.75 or top.unavailable_count > 0:
        _append_unique(caveats, "missing_reference_data")
        confidence_score *= 0.9
    if episode.quality_penalty > 0:
        _append_unique(caveats, "poor_quality")
        confidence_score *= max(0.4, 1.0 - episode.quality_penalty)
    if episode.duration_s < 1.0:
        _append_unique(caveats, "low_usable_duration")
        confidence_score *= 0.9
    if episode.transient:
        _append_unique(caveats, "transient_only")
        confidence_score *= 0.75
    if len(episode.affected_sensors) > 2:
        _append_unique(caveats, "conflicting_sensor_evidence")
        confidence_score *= 0.9
    confidence_score = _clamp(confidence_score)
    return DenseFinding(
        finding_id=f"dense-{index + 1:03d}",
        episode_id=episode.episode_id,
        likely_origin=likely_origin,
        confidence_score=confidence_score,
        confidence_label=_confidence_label(confidence_score, config=config),
        evidence_windows=evidence_windows,
        alternatives=alternatives,
        caveats=tuple(caveats),
        strongest_location=episode.location,
        median_frequency_hz=episode.median_frequency_hz,
        peak_strength_db=episode.peak_strength_db,
        duration_s=episode.duration_s,
        supporting_window_ids=episode.supporting_window_ids,
    )


def _score_source(
    episode: VibrationEpisode,
    *,
    source: OrderBandSource,
    band_windows: Mapping[int, OrderBandWindow],
) -> _SourceScore:
    evidence: list[DenseFindingEvidenceWindow] = []
    matched_windows = 0
    eligible_windows = 0
    unavailable_count = 0
    band_label_counts: dict[str, int] = {}
    for window_index, frequency_hz in zip(
        episode.supporting_window_ids,
        episode.frequency_path_hz,
        strict=True,
    ):
        window = band_windows.get(window_index)
        if window is None:
            unavailable_count += 1
            evidence.append(_unmatched_window(window_index, frequency_hz))
            continue
        source_bands = tuple(band for band in window.bands if band.source == source)
        available_bands = tuple(band for band in source_bands if _band_available(band))
        if not available_bands:
            unavailable_count += 1
            evidence.append(_unmatched_window(window_index, frequency_hz))
            continue
        eligible_windows += 1
        best = min(available_bands, key=lambda band: _relative_error(frequency_hz, band))
        matched = _band_matches(frequency_hz, best)
        if matched:
            matched_windows += 1
            band_label_counts[best.label] = band_label_counts.get(best.label, 0) + 1
        evidence.append(
            DenseFindingEvidenceWindow(
                window_index=window_index,
                frequency_hz=frequency_hz,
                matched=matched,
                band_label=best.label,
                band_source=best.source,
                band_min_hz=best.min_hz,
                band_max_hz=best.max_hz,
                relative_error=_relative_error(frequency_hz, best),
            )
        )
    total_windows = max(1, len(episode.supporting_window_ids))
    match_ratio = matched_windows / max(1, eligible_windows)
    completeness = eligible_windows / total_windows
    score = _source_confidence(
        match_ratio=match_ratio,
        completeness=completeness,
        episode=episode,
    )
    return _SourceScore(
        source=source,
        origin=_SOURCE_TO_ORIGIN[source],
        score=score,
        match_ratio=match_ratio,
        completeness=completeness,
        matched_windows=matched_windows,
        eligible_windows=eligible_windows,
        best_band_label=_most_common_label(band_label_counts),
        evidence_windows=tuple(evidence),
        unavailable_count=unavailable_count,
    )


def _source_confidence(
    *,
    match_ratio: float,
    completeness: float,
    episode: VibrationEpisode,
) -> float:
    persistence_score = min(1.0, (len(episode.supporting_window_ids) / 5.0) * 0.6)
    persistence_score += min(1.0, episode.duration_s / 3.0) * 0.4
    strength_score = _clamp((episode.peak_strength_db - 6.0) / 24.0)
    confidence = (
        (match_ratio * 0.35)
        + (completeness * 0.20)
        + (_clamp(persistence_score) * 0.15)
        + (strength_score * 0.20)
        + (_localization_score(episode) * 0.10)
    )
    return _clamp(confidence)


def _unknown_confidence(episode: VibrationEpisode, top: _SourceScore) -> float:
    strength_score = _clamp((episode.peak_strength_db - 6.0) / 24.0)
    persistence_score = min(1.0, len(episode.supporting_window_ids) / 5.0)
    localization_score = _localization_score(episode)
    return _clamp(
        (strength_score * 0.40)
        + (persistence_score * 0.30)
        + (localization_score * 0.10)
        + (top.score * 0.20)
    )


def _localization_score(episode: VibrationEpisode) -> float:
    if not episode.location:
        return 0.4
    if len(episode.affected_sensors) <= 1:
        return 1.0
    if len(episode.affected_sensors) == 2:
        return 0.8
    return 0.6


def _alternative(score: _SourceScore) -> DenseFindingAlternative:
    return DenseFindingAlternative(
        source=score.origin,
        score=score.score,
        match_ratio=score.match_ratio,
        matched_windows=score.matched_windows,
        eligible_windows=score.eligible_windows,
        best_band_label=score.best_band_label,
    )


def _unmatched_evidence(episode: VibrationEpisode) -> tuple[DenseFindingEvidenceWindow, ...]:
    return tuple(
        _unmatched_window(window_index, frequency_hz)
        for window_index, frequency_hz in zip(
            episode.supporting_window_ids,
            episode.frequency_path_hz,
            strict=True,
        )
    )


def _unmatched_window(window_index: int, frequency_hz: float) -> DenseFindingEvidenceWindow:
    return DenseFindingEvidenceWindow(
        window_index=window_index,
        frequency_hz=frequency_hz,
        matched=False,
    )


def _band_available(band: OrderBand) -> bool:
    return (
        band.unavailable_reason is None
        and band.center_hz is not None
        and band.min_hz is not None
        and band.max_hz is not None
        and band.min_hz <= band.max_hz
    )


def _band_matches(frequency_hz: float, band: OrderBand) -> bool:
    return (
        band.min_hz is not None
        and band.max_hz is not None
        and band.min_hz <= frequency_hz <= band.max_hz
    )


def _relative_error(frequency_hz: float, band: OrderBand) -> float:
    if band.center_hz is None or band.center_hz <= 0:
        return 1.0
    return abs(frequency_hz - band.center_hz) / band.center_hz


def _most_common_label(counts: Mapping[str, int]) -> str | None:
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _confidence_label(score: float, *, config: DenseFindingConfig) -> DenseConfidenceLabel:
    if score >= config.high_confidence_threshold:
        return "high"
    if score >= config.medium_confidence_threshold:
        return "medium"
    return "low"


def _clamp(value: float) -> float:
    if not isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _append_unique(caveats: list[DenseFindingCaveat], caveat: DenseFindingCaveat) -> None:
    if caveat not in caveats:
        caveats.append(caveat)
