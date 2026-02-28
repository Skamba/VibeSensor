# ruff: noqa: E501
"""Tests for persistence-aware report ranking, transient classification, and peak table behavior.

Verifies that the report pipeline correctly ranks persistent/patterned vibrations
above one-off transient spikes, and that findings are classified appropriately.
"""

from __future__ import annotations

from vibesensor_core.vibration_strength import vibration_strength_db_scalar

from vibesensor.analysis.findings import (
    _build_persistent_peak_findings,
    _classify_peak_type,
)
from vibesensor.analysis.phase_segmentation import DrivingPhase
from vibesensor.analysis.plot_data import (
    _aggregate_fft_spectrum,
    _aggregate_fft_spectrum_raw,
    _spectrogram_from_peaks,
    _spectrogram_from_peaks_raw,
    _top_peaks_table_rows,
)
from vibesensor.analysis.summary import (
    _annotate_peaks_with_order_labels,
    build_findings_for_samples,
    summarize_run_data,
)
from vibesensor.runlog import create_run_metadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metadata(**overrides) -> dict:
    defaults = dict(
        run_id="test-persistence",
        start_time_utc="2025-01-01T00:00:00+00:00",
        sensor_model="ADXL345",
        raw_sample_rate_hz=200,
        feature_interval_s=0.5,
        fft_window_size_samples=256,
        fft_window_type="hann",
        peak_picker_method="max_peak_amp_across_axes",
        accel_scale_g_per_lsb=1.0 / 256.0,
        tire_width_mm=285.0,
        tire_aspect_pct=30.0,
        rim_in=21.0,
        final_drive_ratio=3.08,
        current_gear_ratio=0.64,
    )
    defaults.update(overrides)
    valid_keys = create_run_metadata.__code__.co_varnames
    return create_run_metadata(**{k: v for k, v in defaults.items() if k in valid_keys})


def _sample(
    t_s: float,
    speed_kmh: float,
    peaks: list[dict],
    *,
    vibration_strength_db: float = 20.0,
    strength_bucket: str = "l2",
    client_name: str = "Front Left",
    strength_floor_amp_g: float | None = None,
) -> dict:
    dominant = peaks[0] if peaks else {"hz": 10.0, "amp": 0.01}
    sample = {
        "record_type": "sample",
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": dominant["amp"],
        "accel_y_g": dominant["amp"],
        "accel_z_g": dominant["amp"],
        "dominant_freq_hz": dominant["hz"],
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": strength_bucket,
        "top_peaks": [
            {
                "hz": p["hz"],
                "amp": p["amp"],
                "vibration_strength_db": p.get("vibration_strength_db", vibration_strength_db),
                "strength_bucket": p.get("strength_bucket", strength_bucket),
            }
            for p in peaks
        ],
        "client_name": client_name,
    }
    if strength_floor_amp_g is not None:
        sample["strength_floor_amp_g"] = strength_floor_amp_g
    return sample


# ---------------------------------------------------------------------------
# _classify_peak_type
# ---------------------------------------------------------------------------


class TestClassifyPeakType:
    def test_high_presence_low_burstiness_is_patterned(self) -> None:
        assert _classify_peak_type(presence_ratio=0.80, burstiness=1.5) == "patterned"

    def test_moderate_presence_low_burstiness_is_patterned(self) -> None:
        assert _classify_peak_type(presence_ratio=0.45, burstiness=2.5) == "patterned"

    def test_moderate_presence_moderate_burstiness_is_persistent(self) -> None:
        assert _classify_peak_type(presence_ratio=0.30, burstiness=3.5) == "persistent"

    def test_low_presence_is_transient(self) -> None:
        assert _classify_peak_type(presence_ratio=0.05, burstiness=1.0) == "transient"

    def test_high_burstiness_is_transient(self) -> None:
        assert _classify_peak_type(presence_ratio=0.30, burstiness=8.0) == "transient"

    def test_boundary_patterned(self) -> None:
        assert _classify_peak_type(presence_ratio=0.40, burstiness=2.9) == "patterned"

    def test_boundary_persistent_not_patterned(self) -> None:
        # presence >= 0.15 but < 0.40 → persistent if burstiness < 5
        assert _classify_peak_type(presence_ratio=0.20, burstiness=4.0) == "persistent"


# ---------------------------------------------------------------------------
# FFT spectrum aggregation
# ---------------------------------------------------------------------------


class TestAggregateFFTSpectrum:
    def test_persistent_signal_ranks_above_single_thud(self) -> None:
        """A 25 Hz peak present in all 20 samples should score higher than a
        one-off 50 Hz spike that only appears once, even if the spike is 10× louder."""
        samples = []
        for i in range(20):
            peaks = [{"hz": 25.0, "amp": 0.05}]
            if i == 5:
                # One-off thud at 50 Hz with huge amplitude
                peaks.append({"hz": 50.0, "amp": 0.50})
            samples.append(_sample(float(i) * 0.5, 80.0 + i * 0.5, peaks))

        spectrum = _aggregate_fft_spectrum(samples, freq_bin_hz=2.0)
        spectrum_dict = dict(spectrum)

        # Find the bins closest to 25 Hz and 50 Hz
        persistent_val = spectrum_dict.get(25.0, spectrum_dict.get(26.0, 0.0))
        transient_val = spectrum_dict.get(51.0, spectrum_dict.get(50.0, 0.0))

        assert persistent_val > transient_val, (
            f"Persistent peak ({persistent_val:.4f}) should rank above "
            f"transient spike ({transient_val:.4f}) in diagnostic spectrum"
        )

    def test_raw_spectrum_preserves_max(self) -> None:
        """Raw spectrum should keep the max amplitude for debug purposes."""
        samples = []
        for i in range(10):
            peaks = [{"hz": 25.0, "amp": 0.05}]
            if i == 3:
                peaks.append({"hz": 50.0, "amp": 0.80})
            samples.append(_sample(float(i), 80.0, peaks))

        raw = _aggregate_fft_spectrum_raw(samples, freq_bin_hz=2.0)
        raw_dict = dict(raw)

        # 50 Hz spike should dominate in raw
        spike_val = raw_dict.get(51.0, raw_dict.get(50.0, 0.0))
        assert spike_val >= 0.80

    def test_empty_samples(self) -> None:
        assert _aggregate_fft_spectrum([]) == []
        assert _aggregate_fft_spectrum_raw([]) == []

    def test_persistence_spectrum_uses_run_noise_baseline(self) -> None:
        low_noise_samples = [
            _sample(
                float(i),
                80.0,
                [{"hz": 30.0, "amp": 0.06}],
                strength_floor_amp_g=0.01,
            )
            for i in range(20)
        ]
        high_noise_samples = [
            _sample(
                float(i),
                80.0,
                [{"hz": 30.0, "amp": 0.06}],
                strength_floor_amp_g=0.05,
            )
            for i in range(20)
        ]

        low_noise_score = dict(_aggregate_fft_spectrum(low_noise_samples)).get(31.0, 0.0)
        high_noise_score = dict(_aggregate_fft_spectrum(high_noise_samples)).get(31.0, 0.0)
        assert low_noise_score > high_noise_score


# ---------------------------------------------------------------------------
# Peak table rows
# ---------------------------------------------------------------------------


class TestTopPeaksTableRows:
    def test_persistent_peak_ranks_first(self) -> None:
        """A peak present in all samples should rank above a louder one-off."""
        samples = []
        for i in range(20):
            peaks = [{"hz": 30.0, "amp": 0.04}]
            if i == 0:
                peaks.append({"hz": 80.0, "amp": 1.0})
            samples.append(_sample(float(i) * 0.5, 85.0, peaks))

        rows = _top_peaks_table_rows(samples)
        assert len(rows) >= 2
        # First rank should be the persistent 30 Hz peak
        assert rows[0]["frequency_hz"] == 30.0
        assert rows[0]["presence_ratio"] > 0.5

    def test_persistence_metadata_present(self) -> None:
        samples = [_sample(float(i), 80.0, [{"hz": 15.0, "amp": 0.05}]) for i in range(5)]
        rows = _top_peaks_table_rows(samples)
        assert len(rows) == 1
        row = rows[0]
        assert "presence_ratio" in row
        assert "median_amp_g" in row
        assert "p95_amp_g" in row
        assert "burstiness" in row
        assert "persistence_score" in row
        assert "peak_classification" in row
        assert row["presence_ratio"] == 1.0  # Present in all 5 samples

    def test_single_sample_still_works(self) -> None:
        """A single sample must produce valid rows."""
        samples = [_sample(0.0, 80.0, [{"hz": 20.0, "amp": 0.1}])]
        rows = _top_peaks_table_rows(samples)
        assert len(rows) == 1
        assert rows[0]["max_amp_g"] == 0.1
        assert rows[0]["presence_ratio"] == 1.0

    def test_damped_ringdown_ranks_below_sustained(self) -> None:
        """A damped ringdown (high initial amp, decaying) should rank below sustained constant amplitude."""
        samples = []
        for i in range(20):
            sustained_peaks = [{"hz": 25.0, "amp": 0.03}]
            if i < 3:
                # Damped ringdown at 60 Hz: starts loud, decays
                ringdown_amp = 0.5 * (0.3**i)
                sustained_peaks.append({"hz": 60.0, "amp": ringdown_amp})
            samples.append(_sample(float(i) * 0.5, 85.0, sustained_peaks))

        rows = _top_peaks_table_rows(samples)
        freq_ranks = {row["frequency_hz"]: row["rank"] for row in rows}
        assert freq_ranks.get(25.0, 999) < freq_ranks.get(60.0, 999), (
            "Sustained 25 Hz should rank above damped ringdown at 60 Hz"
        )

    def test_strength_db_uses_recorded_floor_and_p95_amp(self) -> None:
        samples = [
            _sample(
                0.0,
                80.0,
                [{"hz": 30.0, "amp": 0.10}],
                strength_floor_amp_g=0.02,
            ),
            _sample(
                0.5,
                82.0,
                [{"hz": 30.0, "amp": 0.20}],
                strength_floor_amp_g=0.04,
            ),
        ]

        rows = _top_peaks_table_rows(samples)
        assert rows
        row = rows[0]
        expected_db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=row["p95_amp_g"],
            floor_amp_g=0.03,
        )
        assert row["strength_floor_amp_g"] == 0.03
        assert row["strength_db"] == expected_db

    def test_typical_speed_band_uses_amplitude_weighting(self) -> None:
        speeds = [40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0]
        amps = [0.001, 0.002, 0.010, 0.080, 0.090, 0.080, 0.010, 0.001]
        samples = [
            _sample(float(idx), speed_kmh, [{"hz": 30.0, "amp": amp}])
            for idx, (speed_kmh, amp) in enumerate(zip(speeds, amps, strict=False))
        ]

        rows = _top_peaks_table_rows(samples, top_n=1, freq_bin_hz=1.0)
        assert rows
        assert rows[0]["typical_speed_band"] == "80-90 km/h"

    def test_typical_speed_band_uses_amplitude_weighted_window(self) -> None:
        samples = []
        for i in range(20):
            speed = 40.0 if i < 12 else 100.0
            amp = 0.02 if i < 12 else 0.09
            samples.append(_sample(float(i), speed, [{"hz": 33.0, "amp": amp}]))

        rows = _top_peaks_table_rows(samples)
        assert rows
        assert rows[0]["typical_speed_band"] == "100-110 km/h"

    def test_frequency_binning_matches_floor_based_spectrum_rules(self) -> None:
        samples = [
            _sample(0.0, 60.0, [{"hz": 10.51, "amp": 0.08}]),
            _sample(0.5, 60.0, [{"hz": 10.52, "amp": 0.07}]),
        ]
        rows = _top_peaks_table_rows(samples, top_n=1, freq_bin_hz=1.0)
        assert rows
        assert rows[0]["frequency_hz"] == 10.0

    def test_typical_and_strongest_speed_bands_stay_consistent(self) -> None:
        samples = []
        for i in range(20):
            speed = 40.0 if i < 12 else 100.0
            amp = 0.02 if i < 12 else 0.09
            samples.append(_sample(float(i), speed, [{"hz": 33.0, "amp": amp}]))

        rows = _top_peaks_table_rows(samples)
        assert rows
        typical_speed_band = str(rows[0].get("typical_speed_band") or "")
        assert typical_speed_band == "100-110 km/h"

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        target = next(
            (f for f in findings if "33" in str(f.get("frequency_hz_or_order", ""))),
            None,
        )
        assert target is not None
        assert str(target.get("strongest_speed_band") or "") == typical_speed_band


# ---------------------------------------------------------------------------
# Persistent peak findings
# ---------------------------------------------------------------------------


class TestBuildPersistentPeakFindings:
    def test_persistent_peak_classified_correctly(self) -> None:
        """A peak in 80% of samples should be patterned, not transient."""
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 40.0, "amp": 0.06}]) for i in range(20)]
        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        persistent = [f for f in findings if f.get("peak_classification") == "patterned"]
        transient = [f for f in findings if f.get("peak_classification") == "transient"]
        assert len(persistent) >= 1
        assert len(transient) == 0

    def test_localized_persistent_peak_confidence_is_high(self) -> None:
        samples: list[dict] = []
        for i in range(20):
            peaks = [{"hz": 40.0, "amp": 0.06}] if i < 16 else []
            samples.append(
                _sample(
                    float(i) * 0.5,
                    80.0,
                    peaks,
                    client_name="Front Left",
                )
            )

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        target = next(
            f
            for f in findings
            if f.get("peak_classification") == "patterned"
            and (
                "41.0" in str(f.get("frequency_hz_or_order", ""))
                or "40.0" in str(f.get("frequency_hz_or_order", ""))
            )
        )
        assert float(target.get("confidence_0_to_1", 0.0)) >= 0.50

    def test_uniform_multi_sensor_peak_confidence_is_penalized(self) -> None:
        locations = ["Front Left", "Front Right", "Rear Left", "Rear Right"]
        samples: list[dict] = []
        for i in range(20):
            peaks = [{"hz": 40.0, "amp": 0.06}] if i < 16 else []
            samples.append(
                _sample(
                    float(i) * 0.5,
                    80.0,
                    peaks,
                    client_name=locations[i % len(locations)],
                )
            )

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        candidates = [
            f
            for f in findings
            if (
                "41.0" in str(f.get("frequency_hz_or_order", ""))
                or "40.0" in str(f.get("frequency_hz_or_order", ""))
            )
        ]
        assert candidates
        assert max(float(f.get("confidence_0_to_1", 0.0)) for f in candidates) <= 0.35

    def test_negligible_strength_persistent_peak_confidence_is_capped(self) -> None:
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 40.0, "amp": 0.002}]) for i in range(20)]

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        candidates = [
            f
            for f in findings
            if (
                "41.0" in str(f.get("frequency_hz_or_order", ""))
                or "40.0" in str(f.get("frequency_hz_or_order", ""))
            )
            and str(f.get("peak_classification") or "") in {"patterned", "persistent"}
        ]
        assert candidates
        assert max(float(f.get("confidence_0_to_1", 0.0)) for f in candidates) <= 0.35

    def test_single_thud_classified_as_transient(self) -> None:
        """A peak that appears in only 1 of 20 samples should be transient."""
        samples = []
        for i in range(20):
            peaks = [{"hz": 10.0, "amp": 0.01}]
            if i == 5:
                peaks.append({"hz": 99.0, "amp": 1.0})  # one-off thud
            samples.append(_sample(float(i) * 0.5, 80.0, peaks))

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        thud_findings = [f for f in findings if "99" in str(f.get("frequency_hz_or_order", ""))]
        assert len(thud_findings) >= 1
        assert thud_findings[0]["peak_classification"] == "transient"
        assert thud_findings[0]["suspected_source"] == "transient_impact"

    def test_transient_confidence_capped_low(self) -> None:
        """Transient findings should never get high confidence."""
        samples = []
        for i in range(20):
            peaks = [{"hz": 10.0, "amp": 0.01}]
            if i == 3:
                peaks.append({"hz": 55.0, "amp": 2.0})
            samples.append(_sample(float(i) * 0.5, 80.0, peaks))

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        transient = [f for f in findings if f.get("peak_classification") == "transient"]
        for f in transient:
            assert float(f.get("confidence_0_to_1", 0)) <= 0.25

    def test_order_freqs_excluded(self) -> None:
        """Peaks already claimed by order findings should be excluded."""
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 40.0, "amp": 0.06}]) for i in range(20)]
        findings_with = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs={40.0},
            accel_units="g",
            lang="en",
        )
        findings_without = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        # With the frequency excluded, there should be fewer findings
        assert len(findings_with) < len(findings_without)

    def test_repeated_random_impacts_classified_as_transient(self) -> None:
        """Multiple random one-off impacts at different frequencies should not become persistent findings."""
        samples = []
        for i in range(20):
            peaks = [{"hz": 10.0, "amp": 0.01}]
            # Random impacts at different frequencies
            if i in (2, 7, 12, 17):
                impact_hz = 50.0 + i * 5.0  # Different frequency each time
                peaks.append({"hz": impact_hz, "amp": 0.8})
            samples.append(_sample(float(i) * 0.5, 80.0, peaks))

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        # Impact frequencies are each unique (60, 85, 110, 135 Hz) —
        # each appears in only 1/20 samples → transient.
        impact_findings = [
            f
            for f in findings
            if f.get("peak_classification") != "transient"
            and float(str(f.get("frequency_hz_or_order", "0 Hz")).split()[0]) >= 50.0
        ]
        assert len(impact_findings) == 0, (
            "Random one-off impacts at distinct frequencies should all be transient"
        )

    def test_persistent_peak_speed_band_uses_amplitude_weighting(self) -> None:
        speeds = [40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0]
        amps = [0.001, 0.002, 0.010, 0.080, 0.090, 0.080, 0.010, 0.001]
        samples = [
            _sample(float(idx), speed_kmh, [{"hz": 30.0, "amp": amp}])
            for idx, (speed_kmh, amp) in enumerate(zip(speeds, amps, strict=False))
        ]

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        finding = next(
            f for f in findings if str(f.get("frequency_hz_or_order") or "").startswith("31.0")
        )
        assert finding.get("strongest_speed_band") == "80-90 km/h"

    def test_run_noise_baseline_lowers_confidence_for_borderline_peak(self) -> None:
        low_noise_samples = [
            _sample(
                float(i) * 0.5,
                80.0,
                [{"hz": 30.0, "amp": 0.06}],
                strength_floor_amp_g=0.01,
            )
            for i in range(20)
        ]
        high_noise_samples = [
            _sample(
                float(i) * 0.5,
                80.0,
                [{"hz": 30.0, "amp": 0.06}],
                strength_floor_amp_g=0.05,
            )
            for i in range(20)
        ]

        findings_low = _build_persistent_peak_findings(
            samples=low_noise_samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        findings_high = _build_persistent_peak_findings(
            samples=high_noise_samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )

        confidence_low = max(float(f.get("confidence_0_to_1") or 0.0) for f in findings_low)
        confidence_high = max(float(f.get("confidence_0_to_1") or 0.0) for f in findings_high)
        assert confidence_low > confidence_high

        metrics = dict(findings_low[0].get("evidence_metrics") or {})
        assert "run_noise_baseline_g" in metrics
        assert "median_relative_to_run_noise" in metrics
        assert "p95_relative_to_run_noise" in metrics

    def test_uniform_moderate_presence_peak_is_baseline_noise(self) -> None:
        """Issue #140: 25 Hz in ~30% of samples across all locations/speeds -> baseline noise."""
        locations = ["Front Left", "Front Right", "Rear Left", "Rear Right"]
        speeds = [35.0, 55.0, 75.0, 95.0]
        samples = []
        for speed in speeds:
            for location in locations:
                for rep in range(3):
                    peaks = [{"hz": 10.0, "amp": 0.01}]
                    if rep == 0:
                        amp = 0.20 if (speed, location) == (35.0, "Front Left") else 0.05
                        peaks.append({"hz": 25.0, "amp": amp})
                    samples.append(
                        _sample(float(len(samples)) * 0.5, speed, peaks, client_name=location)
                    )

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        target = [f for f in findings if "25" in str(f.get("frequency_hz_or_order", ""))]
        assert target
        assert target[0]["peak_classification"] == "baseline_noise"

        rows = _top_peaks_table_rows(samples, top_n=12, freq_bin_hz=1.0)
        row_25 = next(
            (row for row in rows if abs(float(row.get("frequency_hz", 0.0)) - 25.0) <= 0.5), None
        )
        assert row_25 is not None
        assert row_25["peak_classification"] == "baseline_noise"

    def test_localized_moderate_presence_peak_remains_persistent(self) -> None:
        """Issue #140: same ~30% 25 Hz peak at one location should stay persistent."""
        locations = ["Front Left", "Front Right", "Rear Left", "Rear Right"]
        speeds = [35.0, 55.0, 75.0, 95.0]
        samples = []
        for speed in speeds:
            for location in locations:
                for rep in range(3):
                    peaks = [{"hz": 10.0, "amp": 0.01}]
                    if location == "Front Left":
                        amp = 0.20 if (speed, rep) == (35.0, 0) else 0.05
                        peaks.append({"hz": 25.0, "amp": amp})
                    samples.append(
                        _sample(float(len(samples)) * 0.5, speed, peaks, client_name=location)
                    )

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        target = [f for f in findings if "25" in str(f.get("frequency_hz_or_order", ""))]
        assert target
        assert target[0]["peak_classification"] == "persistent"

    def test_strongest_speed_band_uses_amplitude_weighted_window(self) -> None:
        """Issue #149: strongest speed band should reflect where peak is strongest."""
        samples: list[dict] = []
        for idx, speed in enumerate(range(40, 121)):
            amp = 0.08 if 70 <= speed <= 90 else 0.01
            samples.append(
                _sample(
                    float(idx) * 0.5,
                    float(speed),
                    [{"hz": 43.0, "amp": amp}],
                )
            )

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        target = next(
            (f for f in findings if "43" in str(f.get("frequency_hz_or_order", ""))),
            None,
        )

        assert target is not None
        speed_band = str(target.get("strongest_speed_band") or "")
        assert speed_band
        assert speed_band != "40-120 km/h"
        assert speed_band in {"70-80 km/h", "80-90 km/h"}


# ---------------------------------------------------------------------------
# Integration: summarize_run_data behavior
# ---------------------------------------------------------------------------


class TestSummarizeRunDataPersistence:
    def test_thud_does_not_become_top_finding(self) -> None:
        """In a mixed run with sustained vibration + a single thud, the thud
        should not be the top likely cause."""
        metadata = _make_metadata()
        samples = []
        for i in range(30):
            # Sustained 15 Hz vibration (consistent with wheel order)
            peaks = [{"hz": 15.0, "amp": 0.05}]
            if i == 10:
                # One massive thud at 120 Hz
                peaks.append({"hz": 120.0, "amp": 2.0})
            samples.append(_sample(float(i) * 0.5, 80.0 + i * 0.5, peaks))

        summary = summarize_run_data(metadata, samples, lang="en")
        findings = summary.get("findings", [])
        # Filter to non-reference findings
        diag_findings = [f for f in findings if not str(f.get("finding_id", "")).startswith("REF_")]

        if diag_findings:
            top = diag_findings[0]
            # The top finding should NOT be a transient_impact
            assert top.get("suspected_source") != "transient_impact", (
                f"Top finding should not be a transient impact, got: {top.get('suspected_source')}"
            )

    def test_persistent_signal_becomes_top_finding(self) -> None:
        """A signal present in all samples should rank as a top finding."""
        metadata = _make_metadata()
        samples = [
            _sample(float(i) * 0.5, 80.0 + i * 0.3, [{"hz": 25.0, "amp": 0.06}]) for i in range(30)
        ]

        summary = summarize_run_data(metadata, samples, lang="en")
        findings = summary.get("findings", [])
        diag_findings = [f for f in findings if not str(f.get("finding_id", "")).startswith("REF_")]

        assert len(diag_findings) >= 1
        # Check that at least one finding references 25 Hz
        found_25hz = any("25" in str(f.get("frequency_hz_or_order", "")) for f in diag_findings)
        assert found_25hz, "25 Hz persistent signal should appear in findings"

    def test_plots_contain_persistence_spectrum(self) -> None:
        """The plots dict should contain both diagnostic and raw FFT spectra."""
        metadata = _make_metadata()
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 20.0, "amp": 0.04}]) for i in range(10)]
        summary = summarize_run_data(metadata, samples, lang="en")
        plots = summary.get("plots", {})
        assert "fft_spectrum" in plots
        assert "fft_spectrum_raw" in plots

    def test_peaks_table_has_persistence_fields(self) -> None:
        """Peak table rows in plots should include persistence metrics."""
        metadata = _make_metadata()
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 20.0, "amp": 0.04}]) for i in range(10)]
        summary = summarize_run_data(metadata, samples, lang="en")
        peaks_table = summary.get("plots", {}).get("peaks_table", [])
        assert len(peaks_table) >= 1
        row = peaks_table[0]
        assert "presence_ratio" in row
        assert "persistence_score" in row
        assert "burstiness" in row
        assert "peak_classification" in row

    def test_summary_includes_run_noise_baseline(self) -> None:
        metadata = _make_metadata()
        samples = [
            _sample(
                float(i) * 0.5,
                80.0,
                [{"hz": 20.0, "amp": 0.04}],
                strength_floor_amp_g=0.02,
            )
            for i in range(10)
        ]
        summary = summarize_run_data(metadata, samples, lang="en")
        assert summary.get("run_noise_baseline_g") == 0.02

    def test_peaks_table_has_run_noise_relative_metrics(self) -> None:
        metadata = _make_metadata()
        samples = [
            _sample(
                float(i) * 0.5,
                80.0,
                [{"hz": 20.0, "amp": 0.04}],
                strength_floor_amp_g=0.02,
            )
            for i in range(10)
        ]
        summary = summarize_run_data(metadata, samples, lang="en")
        peaks_table = summary.get("plots", {}).get("peaks_table", [])
        assert len(peaks_table) >= 1
        row = peaks_table[0]
        assert "run_noise_baseline_g" in row
        assert "median_vs_run_noise_ratio" in row
        assert "p95_vs_run_noise_ratio" in row

    def test_plots_include_diagnostic_and_raw_spectrograms(self) -> None:
        metadata = _make_metadata()
        samples = []
        for i in range(20):
            peaks = [{"hz": 25.0, "amp": 0.05}]
            if i == 10:
                peaks.append({"hz": 80.0, "amp": 1.2})
            samples.append(_sample(float(i), 80.0, peaks))
        summary = summarize_run_data(metadata, samples, lang="en")
        plots = summary.get("plots", {})
        assert "peaks_spectrogram" in plots
        assert "peaks_spectrogram_raw" in plots

    def test_plots_include_phase_boundaries(self) -> None:
        """plots dict should contain phase_boundaries with t_s, end_t_s, and phase keys."""
        metadata = _make_metadata()
        # Idle samples (speed=0) then accelerating then cruising
        samples = (
            [_sample(float(i), 0.0, [{"hz": 20.0, "amp": 0.02}]) for i in range(5)]
            + [
                _sample(float(i + 5), float(i + 5) * 10, [{"hz": 20.0, "amp": 0.04}])
                for i in range(5)
            ]
            + [_sample(float(i + 10), 80.0, [{"hz": 20.0, "amp": 0.05}]) for i in range(10)]
        )
        summary = summarize_run_data(metadata, samples, lang="en")
        plots = summary.get("plots", {})
        assert "phase_boundaries" in plots
        boundaries = plots["phase_boundaries"]
        assert isinstance(boundaries, list)
        assert len(boundaries) >= 1
        for entry in boundaries:
            assert "t_s" in entry
            assert "end_t_s" in entry
            assert "phase" in entry
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
            samples.append(_sample(float(i), 90.0, peaks))

        diagnostic = _spectrogram_from_peaks(samples)
        raw = _spectrogram_from_peaks_raw(samples)

        assert diagnostic["max_amp"] < raw["max_amp"]

    def test_diagnostic_spectrogram_suppresses_broadband_near_floor(self) -> None:
        samples = [
            _sample(
                float(i),
                90.0,
                [{"hz": 30.0, "amp": 0.05}],
                strength_floor_amp_g=0.01,
            )
            for i in range(20)
        ]
        broadband_peaks = [
            {"hz": float(hz), "amp": 0.055} for hz in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
        ]
        samples.append(
            _sample(
                21.0,
                90.0,
                broadband_peaks,
                strength_floor_amp_g=0.05,
            )
        )

        diagnostic = _spectrogram_from_peaks(samples)

        assert diagnostic["cells"]
        noisy_col = len(diagnostic["x_bins"]) - 1
        noisy_col_values = [row[noisy_col] for row in diagnostic["cells"]]
        assert max(noisy_col_values) == 0.0


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_schema_without_optional_fields(self) -> None:
        """Samples missing optional fields (vibration_strength_db on peaks)
        should still be processed gracefully."""
        metadata = _make_metadata()
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
        # Should not raise
        summary = summarize_run_data(metadata, samples, lang="en")
        assert summary["rows"] == 10

    def test_peaks_table_still_has_max_amp_g(self) -> None:
        """Existing consumers relying on max_amp_g should still find it."""
        samples = [_sample(float(i), 80.0, [{"hz": 20.0, "amp": 0.05}]) for i in range(5)]
        rows = _top_peaks_table_rows(samples)
        assert len(rows) >= 1
        assert "max_amp_g" in rows[0]
        assert rows[0]["max_amp_g"] == 0.05

    def test_build_findings_for_samples_works(self) -> None:
        """Public API build_findings_for_samples should still work."""
        metadata = _make_metadata()
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 15.0, "amp": 0.02}]) for i in range(15)]
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# Phase-aware persistent peak findings (TODO-4)
# ---------------------------------------------------------------------------


class TestPersistentPeakFindingsPhaseAwareness:
    """Tests that _build_persistent_peak_findings produces correct phase_presence output."""

    def test_phase_presence_is_none_without_phases(self) -> None:
        """Without per_sample_phases the phase_presence field should be None."""
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 40.0, "amp": 0.06}]) for i in range(20)]
        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
        )
        assert findings
        for f in findings:
            assert f.get("phase_presence") is None

    def test_phase_presence_populated_when_phases_provided(self) -> None:
        """With per_sample_phases, phase_presence should be a dict with presence ratios."""
        samples = [_sample(float(i) * 0.5, 60.0, [{"hz": 40.0, "amp": 0.06}]) for i in range(20)]
        per_sample_phases = [DrivingPhase.CRUISE] * 20
        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
            per_sample_phases=per_sample_phases,
        )
        # bin_center for 40 Hz with freq_bin_hz=2.0 → 41.0 Hz
        peak_findings = [f for f in findings if "41" in str(f.get("frequency_hz_or_order", ""))]
        assert peak_findings, "Expected at least one finding near 40 Hz (bin_center 41.0)"
        f = peak_findings[0]
        phase_presence = f.get("phase_presence")
        assert isinstance(phase_presence, dict), (
            "phase_presence should be a dict when phases provided"
        )
        assert "cruise" in phase_presence, f"Expected 'cruise' key in {phase_presence}"
        assert phase_presence["cruise"] > 0.0

    def test_phase_presence_reflects_dominant_phase(self) -> None:
        """phase_presence ratios should reflect which phase the peak occurs in most."""
        samples: list[dict] = []
        # 12 ACCELERATION samples with the peak, 8 CRUISE samples without
        for i in range(12):
            samples.append(_sample(float(i) * 0.5, 60.0, [{"hz": 50.0, "amp": 0.07}]))
        for i in range(8):
            samples.append(_sample(float(12 + i) * 0.5, 60.0, [{"hz": 10.0, "amp": 0.02}]))
        per_sample_phases = [DrivingPhase.ACCELERATION] * 12 + [DrivingPhase.CRUISE] * 8

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
            per_sample_phases=per_sample_phases,
        )
        # bin_center for 50 Hz with freq_bin_hz=2.0 → 51.0 Hz
        peak_finding = next(
            (f for f in findings if "51" in str(f.get("frequency_hz_or_order", ""))),
            None,
        )
        assert peak_finding is not None, (
            f"Expected finding near 51.0 Hz; got: {[f.get('frequency_hz_or_order') for f in findings]}"
        )
        phase_presence = peak_finding.get("phase_presence")
        assert isinstance(phase_presence, dict)
        # Should show the 50 Hz peak as primarily present in ACCELERATION
        assert "acceleration" in phase_presence
        accel_presence = phase_presence["acceleration"]
        cruise_presence = phase_presence.get("cruise", 0.0)
        assert accel_presence > cruise_presence, (
            f"acceleration presence ({accel_presence}) should exceed cruise ({cruise_presence})"
        )

    def test_phase_presence_multiple_phases(self) -> None:
        """When a peak is observed in multiple phases, all phases appear in phase_presence."""
        samples: list[dict] = []
        phases: list[DrivingPhase] = []
        # 8 CRUISE + 6 ACCELERATION + 6 DECELERATION, all with the same peak
        for i in range(8):
            samples.append(_sample(float(i) * 0.5, 70.0, [{"hz": 35.0, "amp": 0.05}]))
            phases.append(DrivingPhase.CRUISE)
        for i in range(6):
            samples.append(_sample(float(8 + i) * 0.5, 70.0, [{"hz": 35.0, "amp": 0.05}]))
            phases.append(DrivingPhase.ACCELERATION)
        for i in range(6):
            samples.append(_sample(float(14 + i) * 0.5, 70.0, [{"hz": 35.0, "amp": 0.05}]))
            phases.append(DrivingPhase.DECELERATION)

        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
            per_sample_phases=phases,
        )
        # bin_center for 35 Hz with freq_bin_hz=2.0 → floor(35/2)*2 + 1 = 34 + 1 = 35.0 Hz
        peak_finding = next(
            (f for f in findings if "35.0" in str(f.get("frequency_hz_or_order", ""))),
            None,
        )
        assert peak_finding is not None, (
            f"Expected finding at 35.0 Hz; got: {[f.get('frequency_hz_or_order') for f in findings]}"
        )
        phase_presence = peak_finding.get("phase_presence")
        assert isinstance(phase_presence, dict)
        assert "cruise" in phase_presence
        assert "acceleration" in phase_presence
        assert "deceleration" in phase_presence

    def test_phase_presence_values_are_ratios_between_0_and_1(self) -> None:
        """All phase_presence values must be in [0, 1]."""
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 40.0, "amp": 0.06}]) for i in range(20)]
        per_sample_phases = (
            [DrivingPhase.ACCELERATION] * 5
            + [DrivingPhase.CRUISE] * 10
            + [DrivingPhase.DECELERATION] * 5
        )
        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
            per_sample_phases=per_sample_phases,
        )
        for f in findings:
            phase_presence = f.get("phase_presence")
            if phase_presence is not None:
                for phase_key, ratio in phase_presence.items():
                    assert 0.0 <= float(ratio) <= 1.0, (
                        f"phase_presence[{phase_key!r}] = {ratio} is outside [0, 1]"
                    )
                # Values are fractions of peak occurrences per phase, so they sum to ~1.0
                assert abs(sum(float(v) for v in phase_presence.values()) - 1.0) < 1e-9, (
                    "phase_presence values should sum to 1.0"
                )

    def test_phase_presence_via_build_findings_integration(self) -> None:
        """build_findings_for_samples should produce findings with phase_presence populated."""
        metadata = _make_metadata()
        # All CRUISE samples (speed=80 km/h, no acceleration) → segments → cruise phases
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 40.0, "amp": 0.06}]) for i in range(25)]
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        # bin_center for 40 Hz with freq_bin_hz=2.0 → 41.0 Hz
        peak_findings = [f for f in findings if "41" in str(f.get("frequency_hz_or_order", ""))]
        assert peak_findings, (
            "Expected at least one finding near 41.0 Hz (bin-center of 40 Hz input)"
        )
        f = peak_findings[0]
        phase_presence = f.get("phase_presence")
        assert isinstance(phase_presence, dict), (
            "phase_presence should be populated by build_findings_for_samples"
        )
        assert phase_presence, "phase_presence dict should be non-empty"

    def test_phase_presence_ignored_when_length_mismatch(self) -> None:
        """If per_sample_phases has wrong length, phase_presence should be None (graceful fallback)."""
        samples = [_sample(float(i) * 0.5, 80.0, [{"hz": 40.0, "amp": 0.06}]) for i in range(10)]
        # Pass phases with wrong length
        per_sample_phases = [DrivingPhase.CRUISE] * 5  # too short
        findings = _build_persistent_peak_findings(
            samples=samples,
            order_finding_freqs=set(),
            accel_units="g",
            lang="en",
            per_sample_phases=per_sample_phases,
        )
        assert findings
        for f in findings:
            assert f.get("phase_presence") is None, (
                "phase_presence should be None when per_sample_phases length does not match samples"
            )


# ---------------------------------------------------------------------------
# _annotate_peaks_with_order_labels
# ---------------------------------------------------------------------------


class TestAnnotatePeaksWithOrderLabels:
    """Tests for the post-processing step that back-fills order labels onto peaks."""

    def test_order_label_populated_from_finding(self) -> None:
        """Peak row near the finding's median matched_hz gets the order label."""
        summary: dict = {
            "findings": [
                {
                    "finding_id": "F_ORDER",
                    "frequency_hz_or_order": "1x wheel order",
                    "matched_points": [
                        {"matched_hz": 10.8},
                        {"matched_hz": 11.0},
                        {"matched_hz": 11.2},
                    ],
                },
            ],
            "plots": {
                "peaks_table": [
                    {"frequency_hz": 11.0, "order_label": ""},
                    {"frequency_hz": 25.0, "order_label": ""},
                ],
            },
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == "1x wheel order"
        assert summary["plots"]["peaks_table"][1]["order_label"] == ""

    def test_no_annotation_when_frequency_too_far(self) -> None:
        """Peak rows outside tolerance are not annotated."""
        summary: dict = {
            "findings": [
                {
                    "finding_id": "F_ORDER",
                    "frequency_hz_or_order": "1x wheel order",
                    "matched_points": [{"matched_hz": 50.0}],
                },
            ],
            "plots": {
                "peaks_table": [
                    {"frequency_hz": 11.0, "order_label": ""},
                ],
            },
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == ""

    def test_no_crash_when_no_findings(self) -> None:
        """Gracefully handles missing/empty findings."""
        summary: dict = {
            "findings": [],
            "plots": {"peaks_table": [{"frequency_hz": 11.0, "order_label": ""}]},
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == ""

    def test_no_crash_when_no_plots(self) -> None:
        """Gracefully handles missing plots."""
        summary: dict = {"findings": []}
        _annotate_peaks_with_order_labels(summary)  # should not raise

    def test_f_peak_findings_ignored(self) -> None:
        """Non-order findings (F_PEAK) do not annotate peaks."""
        summary: dict = {
            "findings": [
                {
                    "finding_id": "F_PEAK",
                    "frequency_hz_or_order": "41.0 Hz",
                    "matched_points": [{"matched_hz": 41.0}],
                },
            ],
            "plots": {
                "peaks_table": [
                    {"frequency_hz": 41.0, "order_label": ""},
                ],
            },
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == ""

    def test_multiple_order_findings_annotate_different_peaks(self) -> None:
        """Two order findings annotate two different peak rows."""
        summary: dict = {
            "findings": [
                {
                    "finding_id": "F_ORDER",
                    "frequency_hz_or_order": "1x wheel order",
                    "matched_points": [{"matched_hz": 11.0}],
                },
                {
                    "finding_id": "F_ORDER",
                    "frequency_hz_or_order": "2x engine order",
                    "matched_points": [{"matched_hz": 25.0}],
                },
            ],
            "plots": {
                "peaks_table": [
                    {"frequency_hz": 11.0, "order_label": ""},
                    {"frequency_hz": 25.0, "order_label": ""},
                    {"frequency_hz": 60.0, "order_label": ""},
                ],
            },
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == "1x wheel order"
        assert summary["plots"]["peaks_table"][1]["order_label"] == "2x engine order"
        assert summary["plots"]["peaks_table"][2]["order_label"] == ""

    def test_fallback_still_works_in_report_data(self) -> None:
        """Peaks without order_label still fall back to classification in report_data mapping."""
        summary: dict = {
            "findings": [],
            "plots": {
                "peaks_table": [
                    {"frequency_hz": 11.0, "order_label": "", "peak_classification": "patterned"},
                ],
            },
        }
        _annotate_peaks_with_order_labels(summary)
        row = summary["plots"]["peaks_table"][0]
        order_label = str(row.get("order_label") or "").strip()
        # Empty order_label means report_data.py will use classification as fallback
        assert order_label == ""
