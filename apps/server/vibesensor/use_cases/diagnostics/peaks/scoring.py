"""Peak-bin scoring model for diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import log1p

from vibesensor.shared.constants.analysis import NEGLIGIBLE_STRENGTH_MAX_DB, SNR_LOG_DIVISOR
from vibesensor.vibration_strength import vibration_strength_db_scalar

from .._sample_metrics import _effective_baseline_floor
from .classification import classify_peak_type
from .settings import PEAK_CONFIDENCE_SETTINGS
from .statistics import (
    compute_peak_distribution_stats,
    compute_peak_persistence_score,
    compute_peak_spatial_uniformity,
    compute_peak_speed_uniformity,
)


def _presence_ratio_with_location_rescue(
    *,
    count: int,
    n_samples: int,
    total_locations: set[str],
    total_location_sample_counts: Mapping[str, int],
    loc_counts_for_bin: Mapping[str, int],
) -> float:
    """Rescue sparse global presence when one well-sampled location stays consistent."""
    presence = count / max(1, n_samples)
    settings = PEAK_CONFIDENCE_SETTINGS
    if total_location_sample_counts and loc_counts_for_bin:
        for loc in total_locations:
            loc_hits = loc_counts_for_bin.get(loc, 0)
            loc_total = total_location_sample_counts.get(loc, 0)
            if loc_total >= settings.location_rescue_min_samples:
                presence = max(presence, loc_hits / loc_total)
    return presence


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
    """Apply the shared confidence policy for classified peak bins."""
    settings = PEAK_CONFIDENCE_SETTINGS
    snr_score = min(1.0, log1p(raw_snr) / SNR_LOG_DIVISOR)
    spatial_penalty = (
        (settings.spatial_penalty_base + settings.spatial_penalty_range * spatial_concentration)
        if has_location_counts
        else 1.0
    )

    if peak_type == "baseline_noise":
        return max(
            settings.baseline_noise_confidence_min,
            min(
                settings.baseline_noise_confidence_max,
                settings.baseline_noise_confidence_base
                + settings.baseline_noise_presence_weight * presence_ratio,
            ),
        )
    if peak_type == "transient":
        return max(
            settings.transient_confidence_min,
            min(
                settings.transient_confidence_max,
                settings.transient_confidence_base
                + settings.transient_presence_weight * presence_ratio
                + settings.transient_snr_weight * snr_score,
            ),
        )

    base_confidence = max(
        settings.confidence_min,
        min(
            settings.confidence_max,
            settings.confidence_base
            + settings.presence_weight * presence_ratio
            + settings.snr_weight * snr_score
            + settings.burstiness_weight * min(1.0, 1.0 - burstiness / 10.0),
        ),
    )
    confidence = base_confidence * spatial_penalty
    if (
        has_location_counts
        and spatial_concentration <= settings.low_spatial_concentration_threshold
    ):
        confidence = min(confidence, settings.low_spatial_concentration_cap)
    if peak_strength_db < NEGLIGIBLE_STRENGTH_MAX_DB:
        confidence = min(confidence, settings.negligible_strength_cap)
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
        "_sample_count",
        "_spatial_concentration",
        "_spatial_uniformity",
        "_speed_amp_pairs",
        "_speed_uniformity",
        "_total_sample_count",
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
        stats = compute_peak_distribution_stats(amps, floor_vals)
        count = stats.sample_count
        presence_ratio = _presence_ratio_with_location_rescue(
            count=count,
            n_samples=n_samples,
            total_locations=total_locations,
            total_location_sample_counts=total_location_sample_counts,
            loc_counts_for_bin=loc_counts_for_bin,
        )
        effective_floor = _effective_baseline_floor(
            run_noise_baseline_g,
            extra_fallback=stats.mean_floor_amp,
        )
        raw_snr = stats.p95_amp / effective_floor
        total_location_count = len(total_locations)
        spatial_uniformity = compute_peak_spatial_uniformity(
            matching_locations=len(loc_counts_for_bin),
            total_locations=total_location_count,
        )
        speed_uniformity = compute_peak_speed_uniformity(
            speed_bin_counts_for_bin=speed_bin_counts_for_bin,
            total_speed_bin_counts=total_speed_bin_counts,
        )
        spatial_concentration = (
            max(loc_counts_for_bin.values()) / count if loc_counts_for_bin and count > 0 else 1.0
        )
        peak_type = classify_peak_type(
            presence_ratio,
            stats.burstiness,
            snr=raw_snr,
            spatial_uniformity=spatial_uniformity,
            speed_uniformity=speed_uniformity,
        )
        peak_strength_db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=stats.p95_amp,
            floor_amp_g=effective_floor,
        )

        self._bin_center = bin_center
        self._burstiness = stats.burstiness
        self._peak_strength_db = peak_strength_db
        self._peak_type = peak_type
        self._phases_for_bin = dict(phases_for_bin)
        self._presence_ratio = presence_ratio
        self._ranking_score = compute_peak_persistence_score(
            presence_ratio=presence_ratio,
            p95_amp=stats.p95_amp,
        )
        self._raw_snr = raw_snr
        self._sample_count = count
        self._spatial_concentration = spatial_concentration
        self._spatial_uniformity = spatial_uniformity
        self._speed_amp_pairs = list(speed_amp_pairs)
        self._speed_uniformity = speed_uniformity
        self._total_sample_count = n_samples
        self._confidence = _compute_peak_confidence(
            peak_type=peak_type,
            presence_ratio=presence_ratio,
            raw_snr=raw_snr,
            burstiness=stats.burstiness,
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
    def sample_count(self) -> int:
        return self._sample_count

    @property
    def total_sample_count(self) -> int:
        return self._total_sample_count

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
