from __future__ import annotations

from math import sqrt

import numpy as np
import pytest

import vibesensor.vibration_strength as vibration_strength_module
from vibesensor.vibration_strength import (
    compute_vibration_strength_db,
    peak_band_rms_amp_g,
    strength_floor_amp_g,
    vibration_strength_db_scalar,
)

# -- strength_floor_amp_g ----------------------------------------------------


@pytest.mark.parametrize(
    ("freq", "values", "peak_indexes", "exclusion_hz", "hz_range", "broadcast_calls", "expected"),
    [
        pytest.param([], [], [], 1.0, (0, 100), 0, 0.0, id="empty-spectrum"),
        # Peak at 30 Hz excluded (+/-5 Hz): median of [0.1, 0.2, 0.3, 0.4].
        pytest.param(
            [10.0, 20.0, 30.0, 40.0, 50.0],
            [0.1, 0.2, 5.0, 0.3, 0.4],
            [2],
            5.0,
            (0, 100),
            0,
            0.25,
            id="excludes-peak-region-without-broadcast",
        ),
        # Non-monotonic frequencies fall back to the broadcast exclusion mask.
        pytest.param(
            [10.0, 30.0, 20.0, 40.0, 50.0],
            [0.1, 5.0, 0.2, 0.3, 0.4],
            [1],
            5.0,
            (0, 100),
            1,
            0.25,
            id="non-monotonic-uses-broadcast-fallback",
        ),
        # Only 15/25/35 Hz fall inside [10, 40].
        pytest.param(
            [5.0, 15.0, 25.0, 35.0, 45.0],
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [],
            0.0,
            (10, 40),
            0,
            3.0,
            id="respects-min-max-hz",
        ),
        pytest.param(
            [10.0, 20.0], [0.5, 0.6], [99], 1.0, (0, 100), 0, 0.55, id="ignores-bad-peak-index"
        ),
    ],
)
def test_strength_floor_amp_g_cases(
    monkeypatch: pytest.MonkeyPatch,
    freq: list[float],
    values: list[float],
    peak_indexes: list[int],
    exclusion_hz: float,
    hz_range: tuple[float, float],
    broadcast_calls: int,
    expected: float,
) -> None:
    calls = 0
    original = vibration_strength_module._peak_exclusion_mask_broadcast_aligned

    def counting_broadcast(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(**kwargs)

    monkeypatch.setattr(
        vibration_strength_module, "_peak_exclusion_mask_broadcast_aligned", counting_broadcast
    )

    result = strength_floor_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        peak_indexes=peak_indexes,
        exclusion_hz=exclusion_hz,
        min_hz=hz_range[0],
        max_hz=hz_range[1],
    )

    assert result == pytest.approx(expected)
    assert calls == broadcast_calls


# -- peak_band_rms_amp_g ----------------------------------------------------


@pytest.mark.parametrize("center_idx", [-1, 5])
def test_band_rms_center_out_of_range_raises(center_idx: int) -> None:
    with pytest.raises(ValueError, match="center_idx"):
        peak_band_rms_amp_g(
            freq_hz=[10.0],
            combined_spectrum_amp_g=[1.0],
            center_idx=center_idx,
            bandwidth_hz=1.0,
        )


@pytest.mark.parametrize(
    ("freq", "values", "center_idx", "bandwidth_hz", "expected"),
    [
        pytest.param([10.0], [3.0], 0, 0.5, 3.0, id="single-bin"),
        # 10 Hz +/- 1.5 Hz covers 9/10/11 Hz.
        pytest.param(
            [8.0, 9.0, 10.0, 11.0, 12.0],
            [0.0, 1.0, 2.0, 1.0, 0.0],
            2,
            1.5,
            sqrt((1.0 + 4.0 + 1.0) / 3),
            id="multiple-bins",
        ),
        pytest.param(
            [8.0, 9.0, 10.0, 11.0, 12.0],
            [0.0, 1.0, 2.0, 1.0, 2.0],
            4,
            1.5,
            sqrt((1.0 + 4.0) / 2),
            id="last-bin-uses-available-neighbors",
        ),
    ],
)
def test_band_rms_cases(
    freq: list[float],
    values: list[float],
    center_idx: int,
    bandwidth_hz: float,
    expected: float,
) -> None:
    result = peak_band_rms_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        center_idx=center_idx,
        bandwidth_hz=bandwidth_hz,
    )
    assert result == pytest.approx(expected)


_PEAKED_FREQ_HZ = [float(index) for index in range(20)]
_PEAKED_SPECTRUM = (
    [0.001] * 5 + [0.002, 0.004, 0.01, 0.03, 0.06, 0.12, 0.03, 0.01, 0.004, 0.002] + [0.001] * 5
)


@pytest.mark.parametrize(
    "helper_name",
    [
        pytest.param("_aligned_float_arrays", id="repeated-alignment"),
        pytest.param("noise_floor_amp_p20_g", id="public-noise-floor-wrapper"),
        pytest.param("_peak_band_rms_amp_g_aligned", id="full-scan-band-helper"),
        pytest.param("vibration_strength_db_scalar", id="scalar-db-helper"),
        pytest.param("bucket_for_strength", id="scalar-bucket-helper"),
    ],
)
def test_compute_vibration_strength_db_skips_slow_scalar_helpers(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
) -> None:
    """The vectorised hot path must not fall back to per-peak scalar helpers."""
    calls = 0
    original = getattr(vibration_strength_module, helper_name)

    def counting_helper(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(vibration_strength_module, helper_name, counting_helper)

    result = compute_vibration_strength_db(
        freq_hz=_PEAKED_FREQ_HZ,
        combined_spectrum_amp_g_values=_PEAKED_SPECTRUM,
    )

    assert calls == 0
    assert result["vibration_strength_db"] > 0.0
    assert result["strength_bucket"] == result["top_peaks"][0]["strength_bucket"]


def test_compute_vibration_strength_db_does_not_mutate_cached_strength_range_mask() -> None:
    strength_range_mask = np.ones(20, dtype=np.bool_)

    result = compute_vibration_strength_db(
        freq_hz=_PEAKED_FREQ_HZ,
        combined_spectrum_amp_g_values=_PEAKED_SPECTRUM,
        strength_range_mask=strength_range_mask,
    )

    assert np.all(strength_range_mask)
    assert result["vibration_strength_db"] > 0.0


def test_compute_vibration_strength_db_limits_scored_candidates_before_band_rms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scored_candidate_counts: list[int] = []
    original = vibration_strength_module._peak_band_rms_amp_g_from_ranges

    def counting_peak_band_rms_amp_g_from_ranges(
        *,
        combined_spectrum_amp_g: vibration_strength_module.npt.NDArray[
            vibration_strength_module.np.float64
        ],
        left_bounds: vibration_strength_module.npt.NDArray[vibration_strength_module.np.intp],
        right_bounds: vibration_strength_module.npt.NDArray[vibration_strength_module.np.intp],
    ) -> vibration_strength_module.npt.NDArray[vibration_strength_module.np.float64]:
        scored_candidate_counts.append(int(left_bounds.size))
        return original(
            combined_spectrum_amp_g=combined_spectrum_amp_g,
            left_bounds=left_bounds,
            right_bounds=right_bounds,
        )

    monkeypatch.setattr(
        vibration_strength_module,
        "_peak_band_rms_amp_g_from_ranges",
        counting_peak_band_rms_amp_g_from_ranges,
    )

    combined = [
        value
        for peak in [0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21]
        for value in (0.001, peak)
    ]
    combined.append(0.001)

    result = compute_vibration_strength_db(
        freq_hz=[float(index) for index in range(len(combined))],
        combined_spectrum_amp_g_values=combined,
        top_n=4,
    )

    assert scored_candidate_counts == [8]
    assert [peak["hz"] for peak in result["top_peaks"]] == [23.0, 21.0, 19.0, 17.0]
    assert result["vibration_strength_db"] == result["top_peaks"][0]["vibration_strength_db"]


# -- vibration_strength_db_scalar --------------------------------------------


def test_batch_vibration_strength_db_matches_scalar() -> None:
    floor = 0.01
    band_rms = vibration_strength_module.np.array(
        [0.0, 0.01, 0.5, float("nan"), float("inf"), -1.0],
        dtype=vibration_strength_module.np.float64,
    )

    batch = vibration_strength_module._batch_vibration_strength_db_aligned(
        peak_band_rms_amp_g_values=band_rms,
        floor_amp_g=floor,
    )
    expected = vibration_strength_module.np.array(
        [
            vibration_strength_db_scalar(
                peak_band_rms_amp_g=float(value),
                floor_amp_g=floor,
            )
            for value in band_rms
        ],
        dtype=vibration_strength_module.np.float64,
    )

    vibration_strength_module.np.testing.assert_allclose(batch, expected)
