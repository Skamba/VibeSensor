from __future__ import annotations

import pytest

from vibesensor.use_cases.diagnostics.post_run_stft import PostRunStftCoverageState
from vibesensor.use_cases.diagnostics.post_run_vibration_episodes import (
    PostRunVibrationEpisodeConfig,
    detect_post_run_vibration_episodes,
    vibration_episode_debug_rows,
)
from vibesensor.use_cases.diagnostics.post_run_window_features import (
    PostRunWindowAxisDominance,
    PostRunWindowFeature,
    PostRunWindowFeatureQualityFlag,
)
from vibesensor.vibration_strength import StrengthPeak

_RUN_ID = "run-episodes"


def _peak(hz: float, strength_db: float, amp: float = 1.0) -> StrengthPeak:
    return {
        "hz": hz,
        "amp": amp,
        "vibration_strength_db": strength_db,
        "strength_bucket": "l3",
    }


def _feature(
    window_index: int,
    *,
    freq_hz: float,
    strength_db: float,
    client_id: str = "sensor-a",
    location: str = "front_left",
    top_peaks: tuple[StrengthPeak, ...] | None = None,
    quality_flags: tuple[PostRunWindowFeatureQualityFlag, ...] = (),
    coverage_state: PostRunStftCoverageState = "full",
) -> PostRunWindowFeature:
    start_t_s = window_index * 0.5
    end_t_s = start_t_s + 0.5
    peaks = top_peaks if top_peaks is not None else (_peak(freq_hz, strength_db),)
    return PostRunWindowFeature(
        run_id=_RUN_ID,
        client_id=client_id,
        location=location,
        window_index=window_index,
        window_start_t_s=start_t_s,
        window_end_t_s=end_t_s,
        window_center_t_s=start_t_s + 0.25,
        sample_rate_hz=100,
        coverage_state=coverage_state,
        data_quality_flags=(),
        feature_quality_flags=quality_flags,
        dominant_freq_hz=freq_hz,
        vibration_strength_db=strength_db,
        peak_amp_g=1.0,
        noise_floor_amp_g=0.1,
        strength_bucket="l3",
        top_peaks=peaks,
        axis_dominance=PostRunWindowAxisDominance(
            axis="x",
            axis_amp_g=1.0,
            combined_amp_g=1.0,
            ratio=1.0,
        ),
        rms_by_axis_g={"x": 0.5, "y": 0.1, "z": 0.1},
        p2p_by_axis_g={"x": 1.0, "y": 0.2, "z": 0.2},
        max_axis_rms_g=0.5,
        max_axis_p2p_g=1.0,
    )


def test_detects_sustained_single_peak_episode() -> None:
    episodes = detect_post_run_vibration_episodes(
        [_feature(index, freq_hz=10.0, strength_db=18.0) for index in range(4)]
    )

    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.client_id == "sensor-a"
    assert episode.location == "front_left"
    assert episode.supporting_window_ids == (0, 1, 2, 3)
    assert episode.duration_s == pytest.approx(2.0)
    assert episode.median_frequency_hz == pytest.approx(10.0)
    assert episode.peak_strength_db == pytest.approx(18.0)
    assert episode.axis_dominance == "x"
    assert not episode.transient


def test_suppresses_isolated_spike_unless_extreme_transient() -> None:
    normal = detect_post_run_vibration_episodes([_feature(0, freq_hz=10.0, strength_db=18.0)])
    extreme = detect_post_run_vibration_episodes([_feature(0, freq_hz=10.0, strength_db=35.0)])

    assert normal == ()
    assert len(extreme) == 1
    assert extreme[0].transient
    assert "transient_extreme" in extreme[0].quality_penalties


def test_groups_frequency_sweep_when_drift_is_allowed() -> None:
    episodes = detect_post_run_vibration_episodes(
        [
            _feature(0, freq_hz=10.0, strength_db=18.0),
            _feature(1, freq_hz=10.6, strength_db=19.0),
            _feature(2, freq_hz=11.2, strength_db=20.0),
            _feature(3, freq_hz=11.8, strength_db=21.0),
        ],
        config=PostRunVibrationEpisodeConfig(max_frequency_drift_hz=0.75),
    )

    assert len(episodes) == 1
    assert episodes[0].frequency_path_hz == pytest.approx((10.0, 10.6, 11.2, 11.8))
    assert episodes[0].frequency_slope_hz_per_s is not None
    assert episodes[0].frequency_slope_hz_per_s > 0
    assert "frequency_drift" in episodes[0].quality_penalties


def test_keeps_two_concurrent_peak_episodes_separate() -> None:
    features = [
        _feature(
            index,
            freq_hz=8.0,
            strength_db=20.0,
            top_peaks=(_peak(8.0, 20.0), _peak(16.0, 22.0)),
        )
        for index in range(3)
    ]

    episodes = detect_post_run_vibration_episodes(features)

    assert len(episodes) == 2
    assert [episode.median_frequency_hz for episode in episodes] == [8.0, 16.0]
    assert all(episode.supporting_window_ids == (0, 1, 2) for episode in episodes)


def test_records_quality_penalty_for_noisy_feature_stream() -> None:
    episodes = detect_post_run_vibration_episodes(
        [
            _feature(0, freq_hz=12.0, strength_db=18.0),
            _feature(
                1,
                freq_hz=12.1,
                strength_db=18.0,
                quality_flags=("invalid_spectrum_values",),
            ),
            _feature(2, freq_hz=12.0, strength_db=18.0),
        ]
    )

    assert len(episodes) == 1
    assert "quality_flags_present" in episodes[0].quality_penalties
    assert episodes[0].quality_penalty > 0


def test_merges_dropout_gap_when_within_configured_gap() -> None:
    episodes = detect_post_run_vibration_episodes(
        [
            _feature(0, freq_hz=9.0, strength_db=18.0),
            _feature(1, freq_hz=9.1, strength_db=18.0),
            _feature(3, freq_hz=9.2, strength_db=18.0),
            _feature(4, freq_hz=9.1, strength_db=18.0),
        ],
        config=PostRunVibrationEpisodeConfig(merge_gap_s=0.75),
    )

    assert len(episodes) == 1
    assert episodes[0].supporting_window_ids == (0, 1, 3, 4)
    assert "dropout_gap" in episodes[0].quality_penalties


def test_frequency_jump_starts_new_episode() -> None:
    episodes = detect_post_run_vibration_episodes(
        [
            _feature(0, freq_hz=8.0, strength_db=18.0),
            _feature(1, freq_hz=8.1, strength_db=18.0),
            _feature(2, freq_hz=8.0, strength_db=18.0),
            _feature(3, freq_hz=20.0, strength_db=18.0),
            _feature(4, freq_hz=20.1, strength_db=18.0),
            _feature(5, freq_hz=20.0, strength_db=18.0),
        ],
        config=PostRunVibrationEpisodeConfig(max_frequency_drift_hz=0.5),
    )

    assert len(episodes) == 2
    assert [episode.supporting_window_ids for episode in episodes] == [(0, 1, 2), (3, 4, 5)]


def test_vibration_episode_debug_rows_are_stable() -> None:
    episodes = detect_post_run_vibration_episodes(
        [_feature(index, freq_hz=10.0, strength_db=18.0) for index in range(3)]
    )

    rows = vibration_episode_debug_rows(episodes)

    assert len(rows) == 1
    assert rows[0]["window_count"] == 3
    assert rows[0]["median_frequency_hz"] == pytest.approx(10.0)
