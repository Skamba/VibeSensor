# ruff: noqa: E501
from __future__ import annotations

import pytest
from _report_persistence_helpers import build_findings, findings_at_freq, sample, uniform_samples

from vibesensor.analysis.findings.persistent_findings import _classify_peak_type
from vibesensor.analysis.plot_data import (
    _aggregate_fft_spectrum,
    _aggregate_fft_spectrum_raw,
    _top_peaks_table_rows,
)


class TestClassifyPeakType:
    @pytest.mark.parametrize(
        ("presence_ratio", "burstiness", "expected"),
        [
            pytest.param(0.80, 1.5, "patterned", id="high_presence_low_burstiness"),
            pytest.param(0.45, 2.5, "patterned", id="moderate_presence_low_burstiness"),
            pytest.param(0.30, 3.5, "persistent", id="moderate_presence_moderate_burstiness"),
            pytest.param(0.05, 1.0, "transient", id="low_presence"),
            pytest.param(0.30, 8.0, "transient", id="high_burstiness"),
            pytest.param(0.40, 2.9, "patterned", id="boundary_patterned"),
            pytest.param(0.20, 4.0, "persistent", id="boundary_persistent_not_patterned"),
        ],
    )
    def test_classification(self, presence_ratio: float, burstiness: float, expected: str) -> None:
        assert _classify_peak_type(presence_ratio=presence_ratio, burstiness=burstiness) == expected


class TestAggregateFFTSpectrum:
    def test_persistent_signal_ranks_above_single_thud(self) -> None:
        samples = []
        for i in range(20):
            peaks = [{"hz": 25.0, "amp": 0.05}]
            if i == 5:
                peaks.append({"hz": 50.0, "amp": 0.50})
            samples.append(sample(float(i) * 0.5, 80.0 + i * 0.5, peaks))

        spectrum = _aggregate_fft_spectrum(samples, freq_bin_hz=2.0)
        spectrum_dict = dict(spectrum)
        persistent_val = spectrum_dict.get(25.0, spectrum_dict.get(26.0, 0.0))
        transient_val = spectrum_dict.get(51.0, spectrum_dict.get(50.0, 0.0))

        assert persistent_val > transient_val

    def test_raw_spectrum_preserves_max(self) -> None:
        samples = []
        for i in range(10):
            peaks = [{"hz": 25.0, "amp": 0.05}]
            if i == 3:
                peaks.append({"hz": 50.0, "amp": 0.80})
            samples.append(sample(float(i), 80.0, peaks))

        raw = _aggregate_fft_spectrum_raw(samples, freq_bin_hz=2.0)
        raw_dict = dict(raw)
        spike_val = raw_dict.get(51.0, raw_dict.get(50.0, 0.0))
        assert spike_val >= 0.80

    def test_empty_samples(self) -> None:
        assert _aggregate_fft_spectrum([]) == []
        assert _aggregate_fft_spectrum_raw([]) == []

    def test_persistence_spectrum_uses_run_noise_baseline(self) -> None:
        low_noise_samples = uniform_samples(20, 30.0, 0.06, dt=1.0, strength_floor_amp_g=0.01)
        high_noise_samples = uniform_samples(20, 30.0, 0.06, dt=1.0, strength_floor_amp_g=0.05)

        low_noise_score = dict(_aggregate_fft_spectrum(low_noise_samples)).get(31.0, 0.0)
        high_noise_score = dict(_aggregate_fft_spectrum(high_noise_samples)).get(31.0, 0.0)
        assert low_noise_score > high_noise_score


class TestTopPeaksTableRows:
    def test_persistent_peak_ranks_first(self) -> None:
        samples = []
        for i in range(20):
            peaks = [{"hz": 30.0, "amp": 0.04}]
            if i == 0:
                peaks.append({"hz": 80.0, "amp": 1.0})
            samples.append(sample(float(i) * 0.5, 85.0, peaks))

        rows = _top_peaks_table_rows(samples)
        assert len(rows) >= 2
        assert rows[0]["frequency_hz"] == 30.0
        assert rows[0]["presence_ratio"] > 0.5

    def test_persistence_metadata_present(self) -> None:
        rows = _top_peaks_table_rows(uniform_samples(5, 15.0, 0.05, dt=1.0))
        assert len(rows) == 1
        row = rows[0]
        for key in (
            "presence_ratio",
            "median_intensity_db",
            "p95_intensity_db",
            "burstiness",
            "persistence_score",
            "peak_classification",
        ):
            assert key in row
        assert row["presence_ratio"] == 1.0

    def test_single_sample_still_works(self) -> None:
        rows = _top_peaks_table_rows([sample(0.0, 80.0, [{"hz": 20.0, "amp": 0.1}])])
        assert len(rows) == 1
        assert "max_intensity_db" in rows[0]
        assert rows[0]["presence_ratio"] == 1.0

    def test_damped_ringdown_ranks_below_sustained(self) -> None:
        samples = []
        for i in range(20):
            sustained_peaks = [{"hz": 25.0, "amp": 0.03}]
            if i < 3:
                sustained_peaks.append({"hz": 60.0, "amp": 0.5 * (0.3**i)})
            samples.append(sample(float(i) * 0.5, 85.0, sustained_peaks))

        rows = _top_peaks_table_rows(samples)
        freq_ranks = {row["frequency_hz"]: row["rank"] for row in rows}
        assert freq_ranks.get(25.0, 999) < freq_ranks.get(60.0, 999)

    def test_strength_db_uses_recorded_floor_and_p95_amp(self) -> None:
        samples = [
            sample(0.0, 80.0, [{"hz": 30.0, "amp": 0.10}], strength_floor_amp_g=0.02),
            sample(0.5, 82.0, [{"hz": 30.0, "amp": 0.20}], strength_floor_amp_g=0.04),
        ]
        rows = _top_peaks_table_rows(samples)
        assert rows
        row = rows[0]
        assert row["strength_floor_db"] is not None
        assert row["strength_db"] is not None

    def test_typical_speed_band_uses_amplitude_weighting(self) -> None:
        speeds = [40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0]
        amps = [0.001, 0.002, 0.010, 0.080, 0.090, 0.080, 0.010, 0.001]
        samples = [
            sample(float(idx), speed_kmh, [{"hz": 30.0, "amp": amp}])
            for idx, (speed_kmh, amp) in enumerate(zip(speeds, amps, strict=False))
        ]
        rows = _top_peaks_table_rows(samples, top_n=1, freq_bin_hz=1.0)
        assert rows[0]["typical_speed_band"] == "80-90 km/h"

    def test_typical_speed_band_uses_amplitude_weighted_window(self) -> None:
        samples = []
        for i in range(20):
            speed = 40.0 if i < 12 else 100.0
            amp = 0.02 if i < 12 else 0.09
            samples.append(sample(float(i), speed, [{"hz": 33.0, "amp": amp}]))

        rows = _top_peaks_table_rows(samples)
        assert rows[0]["typical_speed_band"] == "100-110 km/h"

    def test_frequency_binning_matches_floor_based_spectrum_rules(self) -> None:
        samples = [
            sample(0.0, 60.0, [{"hz": 10.51, "amp": 0.08}]),
            sample(0.5, 60.0, [{"hz": 10.52, "amp": 0.07}]),
        ]
        rows = _top_peaks_table_rows(samples, top_n=1, freq_bin_hz=1.0)
        assert rows[0]["frequency_hz"] == 10.0

    def test_typical_and_strongest_speed_bands_stay_consistent(self) -> None:
        samples = []
        for i in range(20):
            speed = 40.0 if i < 12 else 100.0
            amp = 0.02 if i < 12 else 0.09
            samples.append(sample(float(i), speed, [{"hz": 33.0, "amp": amp}]))

        rows = _top_peaks_table_rows(samples)
        typical_speed_band = str(rows[0].get("typical_speed_band") or "")
        assert typical_speed_band == "100-110 km/h"

        findings = build_findings(samples)
        target = next(iter(findings_at_freq(findings, "33")), None)
        assert target is not None
        assert str(target.get("strongest_speed_band") or "") == typical_speed_band
