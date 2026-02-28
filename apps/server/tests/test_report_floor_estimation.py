from __future__ import annotations

import pytest
from vibesensor_core.vibration_strength import percentile

from vibesensor.analysis.helpers import _estimate_strength_floor_amp_g, _run_noise_baseline_g
from vibesensor.analysis.plot_data import _top_peaks_table_rows


def _sample(
    peaks: list[tuple[float, float]],
    *,
    floor_amp: float | None = None,
) -> dict[str, object]:
    sample: dict[str, object] = {
        "top_peaks": [{"hz": hz, "amp": amp} for hz, amp in peaks],
        "speed_kmh": 80.0,
    }
    if floor_amp is not None:
        sample["strength_floor_amp_g"] = floor_amp
    return sample


def test_estimate_strength_floor_amp_g_uses_consistent_policy() -> None:
    assert (
        _estimate_strength_floor_amp_g(_sample([(20.0, 0.2), (30.0, 0.3)], floor_amp=0.0)) is None
    )

    amps = [0.1, 0.2, 0.3]
    expected = percentile(sorted(amps), 0.20)
    assert _estimate_strength_floor_amp_g(_sample([(10.0, a) for a in amps])) == pytest.approx(
        expected
    )


def test_run_noise_baseline_and_peak_table_share_floor_estimate() -> None:
    samples = [
        _sample([(30.0, 0.2), (40.0, 0.25)]),  # <3 peaks -> no fallback floor
        _sample([(30.0, 0.35), (50.0, 0.4), (60.0, 0.45)], floor_amp=0.01),
    ]

    baseline = _run_noise_baseline_g(samples)
    assert baseline == pytest.approx(0.01)

    rows = _top_peaks_table_rows(samples, top_n=12, freq_bin_hz=1.0, run_noise_baseline_g=baseline)
    row_30 = next(row for row in rows if float(row["frequency_hz"]) == 30.0)
    assert row_30["strength_floor_amp_g"] == pytest.approx(0.01)
