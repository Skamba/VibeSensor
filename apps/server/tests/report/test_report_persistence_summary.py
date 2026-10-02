"""Persistence summary regressions for peak tables and robust summaries."""

from __future__ import annotations

from _report_persistence_helpers import summarize, uniform_samples
from test_support.report_helpers import (
    analysis_metadata as make_metadata,
)
from test_support.report_helpers import (
    analysis_sample_with_peaks as sample,
)

from vibesensor.adapters.analysis_summary import build_findings_for_samples
from vibesensor.shared.boundaries.sensor_frames.mapping import (
    sensor_frames_to_json_objects,
)
from vibesensor.use_cases.diagnostics.peaks.table import (
    top_peaks_table_rows as _top_peaks_table_rows,
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

    def test_plots_only_carry_peaks_table(self) -> None:
        plots = summarize(uniform_samples(10, 20.0, 0.04)).get("plots", {})
        assert set(plots) == {"peaks_table"}

    def test_peaks_table_has_persistence_fields(self) -> None:
        row = summarize(uniform_samples(10, 20.0, 0.04)).get("plots", {}).get("peaks_table", [])[0]
        for key in ("presence_ratio", "persistence_score", "burstiness", "peak_classification"):
            assert key in row

    def test_summary_includes_run_noise_baseline(self) -> None:
        assert (
            summarize(uniform_samples(10, 20.0, 0.04, strength_floor_amp_g=0.02)).get(
                "run_noise_baseline_db",
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
        assert hasattr(rows[0], "max_intensity_db")

    def test_build_findings_for_samples_works(self) -> None:
        findings = build_findings_for_samples(
            metadata=make_metadata(),
            samples=sensor_frames_to_json_objects(uniform_samples(15, 15.0, 0.02)),
            lang="en",
        )
        assert isinstance(findings, tuple)
