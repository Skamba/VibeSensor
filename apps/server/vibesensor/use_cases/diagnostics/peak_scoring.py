"""Peak-bin scoring model for diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import log1p, sqrt

from vibesensor.shared.constants import NEGLIGIBLE_STRENGTH_MAX_DB, SNR_LOG_DIVISOR
from vibesensor.vibration_strength import percentile
from vibesensor.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from .helpers import _effective_baseline_floor
from .peak_classification import classify_peak_type


def _presence_ratio_with_location_rescue(
    *,
    count: int,
    n_samples: int,
    total_locations: set[str],
    total_location_sample_counts: Mapping[str, int],
    loc_counts_for_bin: Mapping[str, int],
) -> float:
    presence = count / max(1, n_samples)
    if total_location_sample_counts and loc_counts_for_bin:
        for loc in total_locations:
            loc_hits = loc_counts_for_bin.get(loc, 0)
            loc_total = total_location_sample_counts.get(loc, 0)
            if loc_total >= 3:
                presence = max(presence, loc_hits / loc_total)
    return presence


def _compute_speed_uniformity(
    *,
    speed_bin_counts_for_bin: Mapping[str, int],
    total_speed_bin_counts: Mapping[str, int],
) -> float | None:
    if len(total_speed_bin_counts) < 2:
        return None
    hit_rate_sum = 0.0
    hit_rate_sq_sum = 0.0
    hit_rate_count = 0
    for speed_bin, total_count in total_speed_bin_counts.items():
        if total_count <= 0:
            continue
        rate = speed_bin_counts_for_bin.get(speed_bin, 0) / total_count
        hit_rate_sum += rate
        hit_rate_sq_sum += rate * rate
        hit_rate_count += 1
    if hit_rate_count > 1:
        hit_rate_mean = hit_rate_sum / hit_rate_count
        variance = max(0.0, (hit_rate_sq_sum / hit_rate_count) - hit_rate_mean * hit_rate_mean)
        return sqrt(variance)
    if hit_rate_count == 1:
        return 0.0
    return None


def _compute_peak_confidence(
    *,
    peak_type: str,
    presence_ratio: float,
    raw_snr: float,
    burstiness: float,
    spatial_concentration: float,
    has_location_counts: bool,
    peak_strength_db: float,
) -> float:
    snr_score = min(1.0, log1p(raw_snr) / SNR_LOG_DIVISOR)
    spatial_penalty = (0.35 + 0.65 * spatial_concentration) if has_location_counts else 1.0

    if peak_type == "baseline_noise":
        return max(0.02, min(0.12, 0.02 + 0.05 * presence_ratio))
    if peak_type == "transient":
        return max(0.05, min(0.22, 0.05 + 0.10 * presence_ratio + 0.07 * snr_score))

    base_confidence = max(
        0.10,
        min(
            0.75,
            0.10
            + 0.35 * presence_ratio
            + 0.15 * snr_score
            + 0.15 * min(1.0, 1.0 - burstiness / 10.0),
        ),
    )
    confidence = base_confidence * spatial_penalty
    if has_location_counts and spatial_concentration <= 0.35:
        confidence = min(confidence, 0.35)
    if peak_strength_db < NEGLIGIBLE_STRENGTH_MAX_DB:
        confidence = min(confidence, 0.40)
    return confidence


class PeakBin:
    """Scored representation of a single accumulated frequency bin."""

    __slots__ = (
        "_bin_center",
        "_burstiness",
        "_confidence",
        "_peak_strength_db",
        "_peak_type",
        "_phases_for_bin",
        "_presence_ratio",
        "_ranking_score",
        "_raw_snr",
        "_spatial_concentration",
        "_spatial_uniformity",
        "_speed_amp_pairs",
        "_speed_uniformity",
    )

    def __init__(
        self,
        *,
        bin_center: float,
        amps: Sequence[float],
        floor_vals: Sequence[float],
        speed_amp_pairs: Sequence[tuple[float, float]],
        loc_counts_for_bin: Mapping[str, int],
        speed_bin_counts_for_bin: Mapping[str, int],
        phases_for_bin: Mapping[str, int],
        n_samples: int,
        total_locations: set[str],
        total_location_sample_counts: Mapping[str, int],
        total_speed_bin_counts: Mapping[str, int],
        run_noise_baseline_g: float | None,
    ) -> None:
        sorted_amps = sorted(amps)
        count = len(sorted_amps)
        median_amp = percentile(sorted_amps, 0.50) if count >= 2 else sorted_amps[0]
        p95_amp = percentile(sorted_amps, 0.95) if count >= 2 else sorted_amps[-1]
        max_amp = sorted_amps[-1]
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0
        presence_ratio = _presence_ratio_with_location_rescue(
            count=count,
            n_samples=n_samples,
            total_locations=total_locations,
            total_location_sample_counts=total_location_sample_counts,
            loc_counts_for_bin=loc_counts_for_bin,
        )
        mean_floor = sum(floor_vals) / len(floor_vals) if floor_vals else 0.0
        effective_floor = _effective_baseline_floor(
            run_noise_baseline_g,
            extra_fallback=mean_floor,
        )
        raw_snr = p95_amp / effective_floor
        total_location_count = len(total_locations)
        spatial_uniformity = (
            len(loc_counts_for_bin) / total_location_count if total_location_count >= 2 else None
        )
        speed_uniformity = _compute_speed_uniformity(
            speed_bin_counts_for_bin=speed_bin_counts_for_bin,
            total_speed_bin_counts=total_speed_bin_counts,
        )
        spatial_concentration = (
            max(loc_counts_for_bin.values()) / count if loc_counts_for_bin and count > 0 else 1.0
        )
        peak_type = classify_peak_type(
            presence_ratio,
            burstiness,
            snr=raw_snr,
            spatial_uniformity=spatial_uniformity,
            speed_uniformity=speed_uniformity,
        )
        peak_strength_db = canonical_vibration_db(
            peak_band_rms_amp_g=p95_amp,
            floor_amp_g=effective_floor,
        )

        self._bin_center = bin_center
        self._burstiness = burstiness
        self._peak_strength_db = peak_strength_db
        self._peak_type = peak_type
        self._phases_for_bin = dict(phases_for_bin)
        self._presence_ratio = presence_ratio
        self._ranking_score = (presence_ratio**2) * p95_amp
        self._raw_snr = raw_snr
        self._spatial_concentration = spatial_concentration
        self._spatial_uniformity = spatial_uniformity
        self._speed_amp_pairs = list(speed_amp_pairs)
        self._speed_uniformity = speed_uniformity
        self._confidence = _compute_peak_confidence(
            peak_type=peak_type,
            presence_ratio=presence_ratio,
            raw_snr=raw_snr,
            burstiness=burstiness,
            spatial_concentration=spatial_concentration,
            has_location_counts=bool(loc_counts_for_bin),
            peak_strength_db=peak_strength_db,
        )

    @property
    def bin_center(self) -> float:
        return self._bin_center

    @property
    def presence_ratio(self) -> float:
        return self._presence_ratio

    @property
    def burstiness(self) -> float:
        return self._burstiness

    @property
    def snr(self) -> float:
        return self._raw_snr

    @property
    def spatial_uniformity(self) -> float | None:
        return self._spatial_uniformity

    @property
    def speed_uniformity(self) -> float | None:
        return self._speed_uniformity

    @property
    def spatial_concentration(self) -> float:
        return self._spatial_concentration

    @property
    def peak_type(self) -> str:
        return self._peak_type

    @property
    def is_transient(self) -> bool:
        return self._peak_type == "transient"

    @property
    def confidence(self) -> float:
        return self._confidence

    @property
    def ranking_score(self) -> float:
        return self._ranking_score

    @property
    def peak_strength_db(self) -> float:
        return self._peak_strength_db

    @property
    def speed_amp_pairs(self) -> list[tuple[float, float]]:
        return self._speed_amp_pairs

    @property
    def phases_for_bin(self) -> dict[str, int]:
        return self._phases_for_bin
