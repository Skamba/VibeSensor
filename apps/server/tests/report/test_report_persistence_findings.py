# ruff: noqa: E501
from __future__ import annotations

import pytest

from vibesensor.analysis.phase_segmentation import DrivingPhase
from vibesensor.analysis.plot_data import _top_peaks_table_rows
from vibesensor.analysis.summary import _annotate_peaks_with_order_labels
from vibesensor.analysis.summary import build_findings_for_samples

from _report_persistence_helpers import build_findings
from _report_persistence_helpers import findings_at_freq
from _report_persistence_helpers import make_metadata
from _report_persistence_helpers import sample
from _report_persistence_helpers import uniform_samples


class TestBuildPersistentPeakFindings:
    def test_persistent_peak_classified_correctly(self) -> None:
        findings = build_findings(uniform_samples(20, 40.0, 0.06))
        persistent = [f for f in findings if f.get("peak_classification") == "patterned"]
        transient = [f for f in findings if f.get("peak_classification") == "transient"]
        assert len(persistent) >= 1
        assert len(transient) == 0

    def test_localized_persistent_peak_confidence_is_high(self) -> None:
        samples = []
        for i in range(20):
            peaks = [{"hz": 40.0, "amp": 0.06}] if i < 16 else []
            samples.append(sample(float(i) * 0.5, 80.0, peaks, client_name="Front Left"))

        findings = build_findings(samples)
        target = next(
            f
            for f in findings
            if f.get("peak_classification") == "patterned" and findings_at_freq([f], "41.0", "40.0")
        )
        assert float(target.get("confidence_0_to_1", 0.0)) >= 0.50

    def test_uniform_multi_sensor_peak_confidence_is_penalized(self) -> None:
        locations = ["Front Left", "Front Right", "Rear Left", "Rear Right"]
        samples = []
        for i in range(20):
            peaks = [{"hz": 40.0, "amp": 0.06}] if i < 16 else []
            samples.append(sample(float(i) * 0.5, 80.0, peaks, client_name=locations[i % len(locations)]))

        findings = build_findings(samples)
        candidates = findings_at_freq(findings, "41.0", "40.0")
        assert max(float(f.get("confidence_0_to_1", 0.0)) for f in candidates) <= 0.35

    def test_negligible_strength_persistent_peak_confidence_is_capped(self) -> None:
        findings = build_findings(uniform_samples(20, 40.0, 0.002))
        candidates = [
            f
            for f in findings_at_freq(findings, "41.0", "40.0")
            if str(f.get("peak_classification") or "") in {"patterned", "persistent"}
        ]
        assert max(float(f.get("confidence_0_to_1", 0.0)) for f in candidates) <= 0.40

    def test_single_thud_classified_as_transient(self) -> None:
        samples = []
        for i in range(20):
            peaks = [{"hz": 10.0, "amp": 0.01}]
            if i == 5:
                peaks.append({"hz": 99.0, "amp": 1.0})
            samples.append(sample(float(i) * 0.5, 80.0, peaks))

        findings = build_findings(samples)
        thud_findings = findings_at_freq(findings, "99")
        assert thud_findings[0]["peak_classification"] == "transient"
        assert thud_findings[0]["suspected_source"] == "transient_impact"

    def test_transient_confidence_capped_low(self) -> None:
        samples = []
        for i in range(20):
            peaks = [{"hz": 10.0, "amp": 0.01}]
            if i == 3:
                peaks.append({"hz": 55.0, "amp": 2.0})
            samples.append(sample(float(i) * 0.5, 80.0, peaks))

        transient = [f for f in build_findings(samples) if f.get("peak_classification") == "transient"]
        for finding in transient:
            assert float(finding.get("confidence_0_to_1", 0)) <= 0.25

    def test_order_freqs_excluded(self) -> None:
        findings_with = build_findings(uniform_samples(20, 40.0, 0.06), order_finding_freqs={40.0})
        findings_without = build_findings(uniform_samples(20, 40.0, 0.06))
        assert len(findings_with) < len(findings_without)

    def test_repeated_random_impacts_classified_as_transient(self) -> None:
        samples = []
        for i in range(20):
            peaks = [{"hz": 10.0, "amp": 0.01}]
            if i in (2, 7, 12, 17):
                peaks.append({"hz": 50.0 + i * 5.0, "amp": 0.8})
            samples.append(sample(float(i) * 0.5, 80.0, peaks))

        impact_findings = [
            f
            for f in build_findings(samples)
            if f.get("peak_classification") != "transient"
            and float(str(f.get("frequency_hz_or_order", "0 Hz")).split()[0]) >= 50.0
        ]
        assert len(impact_findings) == 0

    def test_persistent_peak_speed_band_uses_amplitude_weighting(self) -> None:
        speeds = [40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0]
        amps = [0.001, 0.002, 0.010, 0.080, 0.090, 0.080, 0.010, 0.001]
        samples = [
            sample(float(idx), speed_kmh, [{"hz": 30.0, "amp": amp}])
            for idx, (speed_kmh, amp) in enumerate(zip(speeds, amps, strict=False))
        ]
        findings = build_findings(samples)
        finding = next(f for f in findings if str(f.get("frequency_hz_or_order") or "").startswith("31.0"))
        assert finding.get("strongest_speed_band") == "80-90 km/h"

    def test_run_noise_baseline_lowers_confidence_for_borderline_peak(self) -> None:
        findings_low = build_findings(uniform_samples(20, 30.0, 0.06, strength_floor_amp_g=0.01))
        findings_high = build_findings(uniform_samples(20, 30.0, 0.06, strength_floor_amp_g=0.05))
        confidence_low = max(float(f.get("confidence_0_to_1") or 0.0) for f in findings_low)
        confidence_high = max(float(f.get("confidence_0_to_1") or 0.0) for f in findings_high)
        assert confidence_low > confidence_high
        metrics = dict(findings_low[0].get("evidence_metrics") or {})
        assert "run_noise_baseline_db" in metrics
        assert "median_relative_to_run_noise" in metrics
        assert "p95_relative_to_run_noise" in metrics

    def test_uniform_moderate_presence_peak_is_baseline_noise(self) -> None:
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
                    samples.append(sample(float(len(samples)) * 0.5, speed, peaks, client_name=location))

        findings = build_findings(samples)
        target = findings_at_freq(findings, "25")
        assert target[0]["peak_classification"] == "baseline_noise"

        rows = _top_peaks_table_rows(samples, top_n=12, freq_bin_hz=1.0)
        row_25 = next((row for row in rows if abs(float(row.get("frequency_hz", 0.0)) - 25.0) <= 0.5), None)
        assert row_25 is not None
        assert row_25["peak_classification"] == "baseline_noise"

    def test_localized_moderate_presence_peak_remains_persistent(self) -> None:
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
                    samples.append(sample(float(len(samples)) * 0.5, speed, peaks, client_name=location))

        findings = build_findings(samples)
        target = findings_at_freq(findings, "25")
        assert target[0]["peak_classification"] == "persistent"

    def test_strongest_speed_band_uses_amplitude_weighted_window(self) -> None:
        samples = []
        for idx, speed in enumerate(range(40, 121)):
            amp = 0.08 if 70 <= speed <= 90 else 0.01
            samples.append(sample(float(idx) * 0.5, float(speed), [{"hz": 43.0, "amp": amp}]))

        findings = build_findings(samples)
        target = next(iter(findings_at_freq(findings, "43")), None)
        assert target is not None
        speed_band = str(target.get("strongest_speed_band") or "")
        assert speed_band in {"70-80 km/h", "80-90 km/h"}


class TestPersistentPeakFindingsPhaseAwareness:
    def test_phase_presence_is_none_without_phases(self) -> None:
        findings = build_findings(uniform_samples(20, 40.0, 0.06))
        for finding in findings:
            assert finding.get("phase_presence") is None

    def test_phase_presence_populated_when_phases_provided(self) -> None:
        findings = build_findings(
            uniform_samples(20, 40.0, 0.06, speed=60.0),
            per_sample_phases=[DrivingPhase.CRUISE] * 20,
        )
        phase_presence = findings_at_freq(findings, "41")[0].get("phase_presence")
        assert isinstance(phase_presence, dict)
        assert phase_presence["cruise"] > 0.0

    def test_phase_presence_reflects_dominant_phase(self) -> None:
        samples = []
        for i in range(12):
            samples.append(sample(float(i) * 0.5, 60.0, [{"hz": 50.0, "amp": 0.07}]))
        for i in range(8):
            samples.append(sample(float(12 + i) * 0.5, 60.0, [{"hz": 10.0, "amp": 0.02}]))
        findings = build_findings(
            samples,
            per_sample_phases=[DrivingPhase.ACCELERATION] * 12 + [DrivingPhase.CRUISE] * 8,
        )
        phase_presence = next(iter(findings_at_freq(findings, "51")), None).get("phase_presence")
        assert phase_presence["acceleration"] > phase_presence.get("cruise", 0.0)

    def test_phase_presence_multiple_phases(self) -> None:
        samples = []
        phases = []
        for i in range(8):
            samples.append(sample(float(i) * 0.5, 70.0, [{"hz": 35.0, "amp": 0.05}]))
            phases.append(DrivingPhase.CRUISE)
        for i in range(6):
            samples.append(sample(float(8 + i) * 0.5, 70.0, [{"hz": 35.0, "amp": 0.05}]))
            phases.append(DrivingPhase.ACCELERATION)
        for i in range(6):
            samples.append(sample(float(14 + i) * 0.5, 70.0, [{"hz": 35.0, "amp": 0.05}]))
            phases.append(DrivingPhase.DECELERATION)

        phase_presence = next(iter(findings_at_freq(build_findings(samples, per_sample_phases=phases), "35.0")), None).get("phase_presence")
        assert "cruise" in phase_presence
        assert "acceleration" in phase_presence
        assert "deceleration" in phase_presence

    def test_phase_presence_values_are_ratios_between_0_and_1(self) -> None:
        findings = build_findings(
            uniform_samples(20, 40.0, 0.06),
            per_sample_phases=[DrivingPhase.ACCELERATION] * 5 + [DrivingPhase.CRUISE] * 10 + [DrivingPhase.DECELERATION] * 5,
        )
        for finding in findings:
            phase_presence = finding.get("phase_presence")
            if phase_presence is not None:
                for ratio in phase_presence.values():
                    assert 0.0 <= float(ratio) <= 1.0
                assert abs(sum(float(v) for v in phase_presence.values()) - 1.0) < 1e-9

    def test_phase_presence_via_build_findings_integration(self) -> None:
        findings = build_findings_for_samples(metadata=make_metadata(), samples=uniform_samples(25, 40.0, 0.06), lang="en")
        phase_presence = findings_at_freq(findings, "41")[0].get("phase_presence")
        assert isinstance(phase_presence, dict)
        assert phase_presence

    def test_phase_presence_ignored_when_length_mismatch(self) -> None:
        findings = build_findings(uniform_samples(10, 40.0, 0.06), per_sample_phases=[DrivingPhase.CRUISE] * 5)
        for finding in findings:
            assert finding.get("phase_presence") is None


class TestAnnotatePeaksWithOrderLabels:
    def test_order_label_populated_from_finding(self) -> None:
        summary = {
            "findings": [{"finding_id": "F_ORDER", "frequency_hz_or_order": "1x wheel order", "matched_points": [{"matched_hz": 10.8}, {"matched_hz": 11.0}, {"matched_hz": 11.2}]}],
            "plots": {"peaks_table": [{"frequency_hz": 11.0, "order_label": ""}, {"frequency_hz": 25.0, "order_label": ""}]},
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == "1x wheel order"
        assert summary["plots"]["peaks_table"][1]["order_label"] == ""

    def test_no_annotation_when_frequency_too_far(self) -> None:
        summary = {
            "findings": [{"finding_id": "F_ORDER", "frequency_hz_or_order": "1x wheel order", "matched_points": [{"matched_hz": 50.0}]}],
            "plots": {"peaks_table": [{"frequency_hz": 11.0, "order_label": ""}]},
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == ""

    def test_no_crash_when_no_findings(self) -> None:
        summary = {"findings": [], "plots": {"peaks_table": [{"frequency_hz": 11.0, "order_label": ""}]}}
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == ""

    def test_no_crash_when_no_plots(self) -> None:
        _annotate_peaks_with_order_labels({"findings": []})

    def test_f_peak_findings_ignored(self) -> None:
        summary = {
            "findings": [{"finding_id": "F_PEAK", "frequency_hz_or_order": "41.0 Hz", "matched_points": [{"matched_hz": 41.0}]}],
            "plots": {"peaks_table": [{"frequency_hz": 41.0, "order_label": ""}]},
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == ""

    def test_multiple_order_findings_annotate_different_peaks(self) -> None:
        summary = {
            "findings": [
                {"finding_id": "F_ORDER", "frequency_hz_or_order": "1x wheel order", "matched_points": [{"matched_hz": 11.0}]},
                {"finding_id": "F_ORDER", "frequency_hz_or_order": "2x engine order", "matched_points": [{"matched_hz": 25.0}]},
            ],
            "plots": {"peaks_table": [{"frequency_hz": 11.0, "order_label": ""}, {"frequency_hz": 25.0, "order_label": ""}, {"frequency_hz": 60.0, "order_label": ""}]},
        }
        _annotate_peaks_with_order_labels(summary)
        assert summary["plots"]["peaks_table"][0]["order_label"] == "1x wheel order"
        assert summary["plots"]["peaks_table"][1]["order_label"] == "2x engine order"
        assert summary["plots"]["peaks_table"][2]["order_label"] == ""

    def test_fallback_still_works_in_report_data(self) -> None:
        summary = {"findings": [], "plots": {"peaks_table": [{"frequency_hz": 11.0, "order_label": "", "peak_classification": "patterned"}]}}
        _annotate_peaks_with_order_labels(summary)
        assert str(summary["plots"]["peaks_table"][0].get("order_label") or "").strip() == ""