# ruff: noqa: E501
from __future__ import annotations

from _report_persistence_helpers import make_metadata, sample, summarize, uniform_samples

from vibesensor.analysis import build_findings_for_samples
from vibesensor.analysis.plot_data import (
    _spectrogram_from_peaks,
    _spectrogram_from_peaks_raw,
    _top_peaks_table_rows,
)


class TestSummarizeRunDataPersistence:
    def test_thud_does_not_become_top_finding(self) -> None:
        samples = []
        for i in range(30):
            peaks = [{"hz": 15.0, "amp": 0.05}]
            if i == 10:
                peaks.append({"hz": 120.0, "amp": 2.0})
            samples.append(sample(float(i) * 0.5, 80.0 + i * 0.5, peaks))

        diag_findings = [
            f
            for f in summarize(samples).get("findings", [])
            if not str(f.get("finding_id", "")).startswith("REF_")
        ]
        if diag_findings:
            assert diag_findings[0].get("suspected_source") != "transient_impact"

    def test_persistent_signal_becomes_top_finding(self) -> None:
        samples = [
            sample(float(i) * 0.5, 80.0 + i * 0.3, [{"hz": 25.0, "amp": 0.06}]) for i in range(30)
        ]
        diag_findings = [
            f
            for f in summarize(samples).get("findings", [])
            if not str(f.get("finding_id", "")).startswith("REF_")
        ]
        assert len(diag_findings) >= 1
        assert any("25" in str(f.get("frequency_hz_or_order", "")) for f in diag_findings)

    def test_plots_contain_persistence_spectrum(self) -> None:
        plots = summarize(uniform_samples(10, 20.0, 0.04)).get("plots", {})
        assert "fft_spectrum" in plots
        assert "fft_spectrum_raw" in plots

    def test_peaks_table_has_persistence_fields(self) -> None:
        row = summarize(uniform_samples(10, 20.0, 0.04)).get("plots", {}).get("peaks_table", [])[0]
        for key in ("presence_ratio", "persistence_score", "burstiness", "peak_classification"):
            assert key in row

    def test_summary_includes_run_noise_baseline(self) -> None:
        assert (
            summarize(uniform_samples(10, 20.0, 0.04, strength_floor_amp_g=0.02)).get(
                "run_noise_baseline_db"
            )
            is not None
        )

    def test_peaks_table_has_run_noise_relative_metrics(self) -> None:
        row = (
            summarize(uniform_samples(10, 20.0, 0.04, strength_floor_amp_g=0.02))
            .get("plots", {})
            .get("peaks_table", [])[0]
        )
        for key in ("run_noise_baseline_db", "median_vs_run_noise_ratio", "p95_vs_run_noise_ratio"):
            assert key in row

    def test_plots_include_diagnostic_and_raw_spectrograms(self) -> None:
        samples = []
        for i in range(20):
            peaks = [{"hz": 25.0, "amp": 0.05}]
            if i == 10:
                peaks.append({"hz": 80.0, "amp": 1.2})
            samples.append(sample(float(i), 80.0, peaks))
        plots = summarize(samples).get("plots", {})
        assert "peaks_spectrogram" in plots
        assert "peaks_spectrogram_raw" in plots

    def test_plots_include_phase_boundaries(self) -> None:
        samples = [sample(float(i), 0.0, [{"hz": 20.0, "amp": 0.02}]) for i in range(5)]
        samples += [
            sample(float(i + 5), float(i + 5) * 10, [{"hz": 20.0, "amp": 0.04}]) for i in range(5)
        ]
        samples += [sample(float(i + 10), 80.0, [{"hz": 20.0, "amp": 0.05}]) for i in range(10)]
        boundaries = summarize(samples).get("plots", {}).get("phase_boundaries")
        assert isinstance(boundaries, list)
        for entry in boundaries:
            assert isinstance(entry["t_s"], float)
            assert isinstance(entry["end_t_s"], float)
            assert isinstance(entry["phase"], str)


class TestSpectrogramPersistence:
    def test_diagnostic_spectrogram_downweights_one_off_thud(self) -> None:
        samples = []
        for i in range(20):
            peaks = [{"hz": 30.0, "amp": 0.06}]
            if i == 7:
                peaks.append({"hz": 70.0, "amp": 1.0})
            samples.append(sample(float(i), 90.0, peaks))

        diagnostic = _spectrogram_from_peaks(samples)
        raw = _spectrogram_from_peaks_raw(samples)
        assert diagnostic["max_amp"] < raw["max_amp"]

    def test_diagnostic_spectrogram_suppresses_broadband_near_floor(self) -> None:
        samples = [
            sample(float(i), 90.0, [{"hz": 30.0, "amp": 0.05}], strength_floor_amp_g=0.01)
            for i in range(20)
        ]
        broadband_peaks = [
            {"hz": float(hz), "amp": 0.055} for hz in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
        ]
        samples.append(sample(21.0, 90.0, broadband_peaks, strength_floor_amp_g=0.05))

        diagnostic = _spectrogram_from_peaks(samples)
        noisy_col = len(diagnostic["x_bins"]) - 1
        noisy_col_values = [row[noisy_col] for row in diagnostic["cells"]]
        assert max(noisy_col_values) == 0.0


class TestRobustness:
    def test_schema_without_optional_fields(self) -> None:
        samples = [
            {
                "record_type": "sample",
                "t_s": float(i),
                "speed_kmh": 80.0,
                "accel_x_g": 0.01,
                "accel_y_g": 0.01,
                "accel_z_g": 0.01,
                "dominant_freq_hz": 15.0,
                "vibration_strength_db": 20.0,
                "strength_bucket": "l2",
                "top_peaks": [{"hz": 15.0, "amp": 0.02}],
                "client_name": "Front Left",
            }
            for i in range(10)
        ]
        assert summarize(samples)["rows"] == 10

    def test_peaks_table_has_max_intensity_db(self) -> None:
        rows = _top_peaks_table_rows(uniform_samples(5, 20.0, 0.05, dt=1.0))
        assert "max_intensity_db" in rows[0]

    def test_build_findings_for_samples_works(self) -> None:
        findings = build_findings_for_samples(
            metadata=make_metadata(), samples=uniform_samples(15, 15.0, 0.02), lang="en"
        )
        assert isinstance(findings, list)
