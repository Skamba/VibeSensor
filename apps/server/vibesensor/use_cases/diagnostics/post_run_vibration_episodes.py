"""Persistent vibration episode detection over dense post-run window features."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import Literal

from vibesensor.shared.fft_analysis import Axis
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.whole_run_json_helpers import set_optional_value
from vibesensor.use_cases.diagnostics.post_run_window_features import (
    PostRunWindowFeature,
    PostRunWindowFeatureQualityFlag,
)

type VibrationEpisodeQualityPenalty = Literal[
    "dropout_gap",
    "frequency_drift",
    "quality_flags_present",
    "short_duration",
    "transient_extreme",
]

__all__ = [
    "PostRunVibrationEpisodeConfig",
    "VibrationEpisode",
    "VibrationEpisodeQualityPenalty",
    "detect_post_run_vibration_episodes",
    "vibration_episode_debug_rows",
]


@dataclass(frozen=True, slots=True)
class PostRunVibrationEpisodeConfig:
    """Deterministic grouping thresholds for dense vibration episodes."""

    min_strength_db: float = 6.0
    extreme_transient_strength_db: float = 30.0
    min_windows: int = 3
    min_duration_s: float = 0.75
    merge_gap_s: float = 0.5
    max_frequency_drift_hz: float = 1.0
    max_relative_frequency_drift_pct: float = 12.0
    max_peaks_per_window: int = 4


@dataclass(frozen=True, slots=True)
class VibrationEpisode:
    """Time-bounded persistent or intentional transient vibration evidence."""

    episode_id: str
    run_id: str
    client_id: str
    location: str
    start_t_s: float
    end_t_s: float
    duration_s: float
    start_window_index: int
    end_window_index: int
    supporting_window_ids: tuple[int, ...]
    frequency_path_hz: tuple[float, ...]
    median_frequency_hz: float
    peak_frequency_hz: float
    frequency_slope_hz_per_s: float | None
    median_strength_db: float
    peak_strength_db: float
    peak_count: int
    axis_dominance: Axis | None
    affected_sensors: tuple[str, ...]
    quality_penalties: tuple[VibrationEpisodeQualityPenalty, ...]
    quality_penalty: float
    transient: bool = False

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "client_id": self.client_id,
            "location": self.location,
            "start_t_s": self.start_t_s,
            "end_t_s": self.end_t_s,
            "duration_s": self.duration_s,
            "start_window_index": self.start_window_index,
            "end_window_index": self.end_window_index,
            "supporting_window_ids": list(self.supporting_window_ids),
            "frequency_path_hz": list(self.frequency_path_hz),
            "median_frequency_hz": self.median_frequency_hz,
            "peak_frequency_hz": self.peak_frequency_hz,
            "median_strength_db": self.median_strength_db,
            "peak_strength_db": self.peak_strength_db,
            "peak_count": self.peak_count,
            "affected_sensors": list(self.affected_sensors),
            "quality_penalties": list(self.quality_penalties),
            "quality_penalty": self.quality_penalty,
            "transient": self.transient,
        }
        set_optional_value(payload, "frequency_slope_hz_per_s", self.frequency_slope_hz_per_s)
        set_optional_value(payload, "axis_dominance", self.axis_dominance)
        return payload


@dataclass(frozen=True, slots=True)
class _PeakCandidate:
    run_id: str
    client_id: str
    location: str
    window_index: int
    window_start_t_s: float
    window_end_t_s: float
    window_center_t_s: float
    frequency_hz: float
    strength_db: float
    axis: Axis | None
    feature_quality_flags: tuple[PostRunWindowFeatureQualityFlag, ...]


@dataclass(slots=True)
class _EpisodeBuilder:
    run_id: str
    client_id: str
    location: str
    candidates: list[_PeakCandidate]

    @property
    def last(self) -> _PeakCandidate:
        return self.candidates[-1]

    def append(self, candidate: _PeakCandidate) -> None:
        self.candidates.append(candidate)


def detect_post_run_vibration_episodes(
    features: Iterable[PostRunWindowFeature],
    *,
    config: PostRunVibrationEpisodeConfig | None = None,
) -> tuple[VibrationEpisode, ...]:
    """Group window-level peaks into deterministic vibration episodes."""

    effective_config = config or PostRunVibrationEpisodeConfig()
    _validate_config(effective_config)
    candidates = _peak_candidates(features, config=effective_config)
    builders: list[_EpisodeBuilder] = []
    for candidate in candidates:
        builder = _best_builder(candidate, builders, config=effective_config)
        if builder is None:
            builders.append(
                _EpisodeBuilder(
                    run_id=candidate.run_id,
                    client_id=candidate.client_id,
                    location=candidate.location,
                    candidates=[candidate],
                )
            )
        else:
            builder.append(candidate)
    episodes = [
        episode
        for index, builder in enumerate(builders)
        if (
            episode := _episode_from_builder(
                builder,
                episode_index=index,
                config=effective_config,
            )
        )
        is not None
    ]
    return tuple(
        sorted(
            episodes,
            key=lambda episode: (
                episode.start_t_s,
                episode.median_frequency_hz,
                episode.episode_id,
            ),
        )
    )


def vibration_episode_debug_rows(
    episodes: Iterable[VibrationEpisode],
) -> tuple[JsonObject, ...]:
    """Return compact debug rows for synthetic episode inspection."""

    return tuple(
        {
            "episode_id": episode.episode_id,
            "client_id": episode.client_id,
            "location": episode.location,
            "start_t_s": episode.start_t_s,
            "end_t_s": episode.end_t_s,
            "duration_s": episode.duration_s,
            "median_frequency_hz": episode.median_frequency_hz,
            "peak_strength_db": episode.peak_strength_db,
            "window_count": len(episode.supporting_window_ids),
            "transient": episode.transient,
            "quality_penalties": list(episode.quality_penalties),
        }
        for episode in episodes
    )


def _validate_config(config: PostRunVibrationEpisodeConfig) -> None:
    if config.min_windows <= 0:
        raise ValueError("episode detection requires min_windows > 0")
    if config.max_peaks_per_window <= 0:
        raise ValueError("episode detection requires max_peaks_per_window > 0")
    for field_name, value in (
        ("min_strength_db", config.min_strength_db),
        ("extreme_transient_strength_db", config.extreme_transient_strength_db),
        ("min_duration_s", config.min_duration_s),
        ("merge_gap_s", config.merge_gap_s),
        ("max_frequency_drift_hz", config.max_frequency_drift_hz),
        ("max_relative_frequency_drift_pct", config.max_relative_frequency_drift_pct),
    ):
        if not isfinite(value) or value < 0:
            raise ValueError(f"episode detection requires {field_name} >= 0")


def _peak_candidates(
    features: Iterable[PostRunWindowFeature],
    *,
    config: PostRunVibrationEpisodeConfig,
) -> tuple[_PeakCandidate, ...]:
    candidates: list[_PeakCandidate] = []
    for feature in features:
        if feature.coverage_state != "full":
            continue
        for peak in feature.top_peaks[: config.max_peaks_per_window]:
            frequency_hz = _positive_float(peak.get("hz"))
            strength_db = _finite_float(peak.get("vibration_strength_db"))
            if frequency_hz is None or strength_db is None or strength_db < config.min_strength_db:
                continue
            candidates.append(
                _PeakCandidate(
                    run_id=feature.run_id,
                    client_id=feature.client_id,
                    location=feature.location,
                    window_index=feature.window_index,
                    window_start_t_s=feature.window_start_t_s,
                    window_end_t_s=feature.window_end_t_s,
                    window_center_t_s=feature.window_center_t_s,
                    frequency_hz=frequency_hz,
                    strength_db=strength_db,
                    axis=feature.axis_dominance.axis,
                    feature_quality_flags=feature.feature_quality_flags,
                )
            )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.client_id,
                candidate.location,
                candidate.window_index,
                candidate.frequency_hz,
                -candidate.strength_db,
            ),
        )
    )


def _best_builder(
    candidate: _PeakCandidate,
    builders: Sequence[_EpisodeBuilder],
    *,
    config: PostRunVibrationEpisodeConfig,
) -> _EpisodeBuilder | None:
    best: _EpisodeBuilder | None = None
    best_delta = float("inf")
    for builder in builders:
        if not _same_sensor(candidate, builder):
            continue
        last = builder.last
        if candidate.window_index <= last.window_index:
            continue
        if candidate.window_start_t_s - last.window_end_t_s > config.merge_gap_s:
            continue
        delta_hz = abs(candidate.frequency_hz - last.frequency_hz)
        if not _frequency_drift_allowed(last.frequency_hz, candidate.frequency_hz, config=config):
            continue
        if delta_hz < best_delta:
            best = builder
            best_delta = delta_hz
    return best


def _same_sensor(candidate: _PeakCandidate, builder: _EpisodeBuilder) -> bool:
    return candidate.client_id == builder.client_id and candidate.location == builder.location


def _frequency_drift_allowed(
    previous_hz: float,
    current_hz: float,
    *,
    config: PostRunVibrationEpisodeConfig,
) -> bool:
    delta_hz = abs(current_hz - previous_hz)
    if delta_hz <= config.max_frequency_drift_hz:
        return True
    relative_pct = (delta_hz / max(previous_hz, current_hz, 1.0)) * 100.0
    return relative_pct <= config.max_relative_frequency_drift_pct


def _episode_from_builder(
    builder: _EpisodeBuilder,
    *,
    episode_index: int,
    config: PostRunVibrationEpisodeConfig,
) -> VibrationEpisode | None:
    candidates = builder.candidates
    strengths = [candidate.strength_db for candidate in candidates]
    frequencies = [candidate.frequency_hz for candidate in candidates]
    start_t_s = candidates[0].window_start_t_s
    end_t_s = candidates[-1].window_end_t_s
    duration_s = max(0.0, end_t_s - start_t_s)
    transient = False
    penalties: list[VibrationEpisodeQualityPenalty] = []
    if _has_dropout_gap(candidates):
        _append_unique(penalties, "dropout_gap")
    if _has_large_episode_drift(frequencies, config=config):
        _append_unique(penalties, "frequency_drift")
    if any(candidate.feature_quality_flags for candidate in candidates):
        _append_unique(penalties, "quality_flags_present")
    persistent = len(candidates) >= config.min_windows and duration_s >= config.min_duration_s
    if not persistent:
        if len(candidates) == 1 and max(strengths) >= config.extreme_transient_strength_db:
            transient = True
            _append_unique(penalties, "transient_extreme")
        else:
            return None
    if duration_s < config.min_duration_s:
        _append_unique(penalties, "short_duration")
    episode_id = (
        f"{builder.client_id}:{builder.location}:"
        f"{candidates[0].window_index}-{candidates[-1].window_index}:"
        f"{round(float(median(frequencies)), 3)}"
    )
    return VibrationEpisode(
        episode_id=episode_id,
        run_id=builder.run_id,
        client_id=builder.client_id,
        location=builder.location,
        start_t_s=start_t_s,
        end_t_s=end_t_s,
        duration_s=duration_s,
        start_window_index=candidates[0].window_index,
        end_window_index=candidates[-1].window_index,
        supporting_window_ids=tuple(candidate.window_index for candidate in candidates),
        frequency_path_hz=tuple(frequencies),
        median_frequency_hz=float(median(frequencies)),
        peak_frequency_hz=max(frequencies),
        frequency_slope_hz_per_s=_frequency_slope(candidates),
        median_strength_db=float(median(strengths)),
        peak_strength_db=max(strengths),
        peak_count=len(candidates),
        axis_dominance=_dominant_axis(candidates),
        affected_sensors=(builder.client_id,),
        quality_penalties=tuple(penalties),
        quality_penalty=_quality_penalty(penalties),
        transient=transient,
    )


def _has_dropout_gap(candidates: Sequence[_PeakCandidate]) -> bool:
    previous: _PeakCandidate | None = None
    for candidate in candidates:
        if previous is not None and candidate.window_index > previous.window_index + 1:
            return True
        previous = candidate
    return False


def _has_large_episode_drift(
    frequencies: Sequence[float],
    *,
    config: PostRunVibrationEpisodeConfig,
) -> bool:
    if len(frequencies) < 2:
        return False
    return (max(frequencies) - min(frequencies)) > (config.max_frequency_drift_hz * 2.0)


def _frequency_slope(candidates: Sequence[_PeakCandidate]) -> float | None:
    if len(candidates) < 2:
        return None
    start = candidates[0]
    end = candidates[-1]
    elapsed_s = end.window_center_t_s - start.window_center_t_s
    if elapsed_s <= 0:
        return None
    return (end.frequency_hz - start.frequency_hz) / elapsed_s


def _dominant_axis(candidates: Sequence[_PeakCandidate]) -> Axis | None:
    counts: dict[Axis, int] = {}
    for candidate in candidates:
        if candidate.axis is not None:
            counts[candidate.axis] = counts.get(candidate.axis, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _quality_penalty(penalties: Sequence[VibrationEpisodeQualityPenalty]) -> float:
    weights: dict[VibrationEpisodeQualityPenalty, float] = {
        "dropout_gap": 0.15,
        "frequency_drift": 0.10,
        "quality_flags_present": 0.15,
        "short_duration": 0.20,
        "transient_extreme": 0.25,
    }
    return min(1.0, sum(weights[penalty] for penalty in penalties))


def _positive_float(value: object) -> float | None:
    parsed = _finite_float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) else None


def _append_unique(
    penalties: list[VibrationEpisodeQualityPenalty],
    penalty: VibrationEpisodeQualityPenalty,
) -> None:
    if penalty not in penalties:
        penalties.append(penalty)
